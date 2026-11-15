#!/usr/bin/env python3
"""Build Mashu's Nix configuration locally and deploy its store closure over SSH."""

import argparse
import ipaddress
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

from scripts.checklist import Checklist
from tests.test_vps import (
    RECOVERY_HOST,
    SSH_OPTIONS,
    TAILSCALE_HOST,
    check_access,
    check_health,
    ssh,
)

ROOT = Path(__file__).resolve().parent


def snapshot() -> Path:
    """Freeze tracked files with Nix's Git fetcher. Ignored files stay outside the store."""
    source = subprocess.run(
        [
            "nix",
            "flake",
            "prefetch",
            "--json",
            f"git+{ROOT.as_uri()}",
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    return Path(json.loads(source)["storePath"])


def build(
    source: Path,
    output: str,
    builders: str,
    out_link: Path | None = None,
) -> str:
    """Build with local platform support or explicitly supplied remote builders."""
    target = f"path:{source}#{output}"
    command = ["sudo", "-n", shutil.which("nom") or "nom", "build"]
    command += ["--max-jobs", "1", "--cores", "2"]
    command += ["--out-link", str(out_link)] if out_link else ["--no-link"]
    if builders == "none":
        builders = ""
    return subprocess.run(
        command + ["--print-out-paths", "--builders", builders, target],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def deployment_guard(host, options, action, profile, report=None):
    """Run the access guard on the deployment host."""
    script = (ROOT / "scripts/deploy_guard.py").read_text()
    arguments = [action] if profile is None else [action, profile]
    return ssh(
        host,
        options,
        f"""import subprocess,tempfile
from pathlib import Path
with tempfile.TemporaryDirectory(prefix='mashu-guard-') as directory:
    script = Path(directory) / 'guard.py'
    script.write_text({script!r})
    subprocess.run(['/usr/bin/python3', str(script), *{arguments!r}], check=True)
""",
        privileged=True,
        on_line=report.feed if report else None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "test", "deploy", "clear-rollback"])
    parser.add_argument("--target-host")
    parser.add_argument("--tailscale-host", default=TAILSCALE_HOST)
    parser.add_argument("--recovery-host", default=RECOVERY_HOST)
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument(
        "--output", default="systemConfigs.mashu", help="Nix output for build only"
    )
    parser.add_argument(
        "--builders",
        default="none",
        help="none uses local builds only; otherwise an explicit SSH builder specification",
    )
    args = parser.parse_args()
    # Use independent SSH when the deployment restarts Tailscale.
    args.target_host = args.target_host or args.recovery_host
    if args.output != "systemConfigs.mashu" and args.action != "build":
        parser.error("--output is only for build")
    for host in [args.target_host, args.tailscale_host, args.recovery_host]:
        if not re.fullmatch(r"[A-Za-z0-9_@.:[\]-]+", host) or host.startswith("-"):
            parser.error("invalid SSH target")
    report = Checklist()
    report.title(
        {
            "deploy": "Deploy · Mashu",
            "build": "Build · Mashu",
            "test": "Verify · Mashu",
            "clear-rollback": "Clear rollback · Mashu",
        }[args.action]
    )
    started = time.monotonic()
    registration_started = False
    try:
        if args.action in ("test", "clear-rollback"):
            check_access(
                args.target_host,
                args.tailscale_host,
                args.recovery_host,
                args.ssh_option,
                report=report,
            )
            check_health(args.target_host, args.ssh_option, report=report)
            if args.action == "clear-rollback":
                with report.step("Clear rollback guard"):
                    deployment_guard(args.target_host, args.ssh_option, "clear", None)
            return 0
        if args.action == "deploy":
            machine = check_access(
                args.target_host,
                args.tailscale_host,
                args.recovery_host,
                args.ssh_option,
                require_tailscale=False,
                report=report,
            )
        with report.step("Build profile"):
            source = snapshot()
            out_link = ROOT / "result" if args.output == "systemConfigs.mashu" else None
            profile = build(source, args.output, args.builders, out_link=out_link)
        if args.action == "build":
            report.line(f"\nBuild output: {profile}")
            return 0
        target = args.target_host
        copy_options = [*SSH_OPTIONS, *args.ssh_option]
        if ":" in target:
            user, separator, address = target.rpartition("@")
            address = str(ipaddress.IPv6Address(address.strip("[]")))
            target = f"{user + separator}[{address}]"
            copy_options += [f"-oHostName={address}"]
        with report.step("Copy store paths"):
            subprocess.run(
                ["nom", "copy", "--to", f"ssh://{target}", profile],
                env=os.environ | {"NIX_SSHOPTS": shlex.join(copy_options)},
                text=True,
                capture_output=True,
                check=True,
            )
        deployment_guard(
            args.target_host, args.ssh_option, "arm", profile, report=report
        )
        registration_started = True
        try:
            with report.step("Activate services"):
                # The built profile includes its native System Manager entry points.
                ssh(
                    args.target_host,
                    args.ssh_option,
                    f"""import subprocess
from pathlib import Path
assert Path('/etc/machine-id').read_text().strip() == {machine!r}, 'Deployment target changed'
for action in ['register-profile', 'activate']:
    subprocess.run([{profile!r} + '/bin/' + action], check=True)
""",
                    privileged=True,
                    timeout=600,
                )
        except subprocess.SubprocessError as error:
            print(f"Activation failed: {error}", file=sys.stderr, flush=True)
            for detail in (
                getattr(error, "stdout", None),
                getattr(error, "stderr", None),
            ):
                if detail:
                    print(detail, file=sys.stderr, flush=True)
            raise
        finally:
            # A failed activation may still have changed the running host.
            try:
                check_access(
                    args.target_host,
                    args.tailscale_host,
                    args.recovery_host,
                    args.ssh_option,
                    expected=machine,
                    attempts=12,
                    report=report,
                )
            except RuntimeError as error:
                print(f"Access check failed: {error}", file=sys.stderr, flush=True)
                raise
            finally:
                check_health(args.target_host, args.ssh_option, report=report)
        with report.step("Disarm rollback"):
            deployment_guard(args.target_host, args.ssh_option, "disarm", profile)
        report.line(
            "\n"
            + report.style(
                f"Deployment complete · {time.monotonic() - started:.0f}s", "32"
            )
        )
    except (
        OSError,
        RuntimeError,
        AssertionError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as error:
        report.fail_active()
        report.line("\n" + report.style(f"Failed: {error}", "31"))
        if isinstance(
            error, (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ):
            for detail in (error.stdout, error.stderr):
                if detail:
                    print(detail, file=sys.stderr)
        if registration_started:
            print(
                "Rollback remains armed for 30 minutes from preflight; "
                "inspect systemctl status mashu-deploy-rollback.timer and .service. "
                "application data migrations are not rolled back automatically.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
