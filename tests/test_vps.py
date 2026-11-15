"""Check Mashu continuity: python -m tests.test_vps."""

import argparse
import io
import ipaddress
import json
import os
import re
import selectors
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from scripts.checklist import Checklist

TAILSCALE_HOST = "mashu"
RECOVERY_HOST = "ubuntu@2603:c025:4005:8f7e:0:b837:618:268c"
SSH_OPTIONS = [
    "-T",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ConnectionAttempts=1",
    "-o",
    "ControlMaster=no",
    "-o",
    "ControlPath=none",
]
IDENTITY = """import json,os,socket
from pathlib import Path
print(json.dumps({'machine':Path('/etc/machine-id').read_text().strip(),
                  'hostname':socket.gethostname(),
                  'address':os.environ['SSH_CONNECTION'].split()[2]}))
"""
HEALTH = (Path(__file__).resolve().parents[1] / "scripts/deploy_health.py").read_text()


def ssh(host, options, script, *, privileged=False, timeout=120, on_line=None):
    command = [
        "ssh",
        *SSH_OPTIONS,
        *options,
        "--",
        host,
        "sudo -n /usr/bin/python3 -" if privileged else "python3 -",
    ]
    if on_line is None:
        return subprocess.run(
            command,
            input=script,
            text=True,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout
    with tempfile.TemporaryFile() as remote_input:
        remote_input.write(script.encode())
        remote_input.seek(0)
        # Keep stderr separate so diagnostics cannot become checklist events.
        with (
            tempfile.TemporaryFile() as errors,
            subprocess.Popen(
                command, stdin=remote_input, stdout=subprocess.PIPE, stderr=errors
            ) as process,
            selectors.DefaultSelector() as selector,
        ):
            output = b""
            pending = b""
            deadline = time.monotonic() + timeout
            try:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(command, timeout)
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                        break
                    output += chunk
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        on_line(line.decode(errors="replace"))
                if pending:
                    on_line(pending.decode(errors="replace"))
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException as error:
                process.kill()
                process.wait()
                if isinstance(error, subprocess.TimeoutExpired):
                    errors.seek(0)
                    error.output = output.decode(errors="replace")
                    error.stderr = errors.read().decode(errors="replace")
                raise
            errors.seek(0)
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    command,
                    output.decode(errors="replace"),
                    errors.read().decode(errors="replace"),
                )
            return output.decode(errors="replace")


def check_access(
    target_host,
    tailscale_host,
    recovery_host,
    options=(),
    expected=None,
    require_tailscale=True,
    attempts=1,
    report=None,
):
    report = report or Checklist()
    report.group("SSH")
    failures = []
    paths = [("public SSH", recovery_host)]
    if target_host != recovery_host:
        paths.append(("deployment SSH", target_host))
    if require_tailscale:
        paths.append(("Tailscale SSH", tailscale_host))
    for label, host in paths:
        report.start(
            {
                "public SSH": "Public connection",
                "deployment SSH": "Deployment connection",
                "Tailscale SSH": "Tailscale connection",
            }[label],
            child=True,
        )
        try:
            for attempt in range(attempts):
                try:
                    identity = json.loads(ssh(host, options, IDENTITY))
                    break
                except subprocess.CalledProcessError as error:
                    if error.returncode != 255 or attempt + 1 == attempts:
                        raise
                    time.sleep(2)
            if identity["hostname"] != "mashu":
                raise RuntimeError(f"Unexpected host through {label}")
            if expected is None:
                expected = identity["machine"]
            if identity["machine"] != expected:
                raise RuntimeError(f"Different machine through {label}")
            address = ipaddress.ip_address(identity["address"])
            tailnet = any(
                address in ipaddress.ip_network(network)
                for network in ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]
            )
            if label == "Tailscale SSH" and not tailnet:
                raise RuntimeError("Tailscale check did not use the tailnet address")
            if label == "public SSH" and tailnet:
                raise RuntimeError("Recovery SSH must work independently of Tailscale")
            report.finish()
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
        ) as error:
            detail = (
                error.stderr
                if isinstance(error, subprocess.CalledProcessError)
                else str(error)
            )
            report.finish(False)
            failures.append(f"{label} ({host}): {detail}")
    if failures:
        raise RuntimeError("\n".join(failures))
    return expected


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_redirect(opener, url, expected):
    try:
        response = opener.open(url, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        assert response.status in (302, 303, 307, 308), (
            f"{url}: expected a login redirect, got HTTP {response.status}"
        )
        location = urlsplit(urljoin(url, response.headers.get("Location", "")))
        # Do not include login state or signed query strings in diagnostics.
        actual = (location.scheme, location.netloc, location.path)
        assert actual == expected, f"{url}: unexpected login destination {actual}"


def check_storage(target_host, options=(), report=None):
    report = report or Checklist()
    try:
        ssh(
            target_host,
            options,
            HEALTH + "\nstorage()",
            privileged=True,
            on_line=report.feed,
        )
    except BaseException:
        report.fail_active()
        raise


def check_health(
    target_host, options=(), report=None, *, probe_runner=True, probe_git=True
):
    report = report or Checklist()
    try:
        ssh(
            target_host,
            options,
            HEALTH + f"\nhealth(probe_runner={probe_runner!r})",
            timeout=240,
            privileged=True,
            on_line=report.feed,
        )
    except BaseException:
        report.fail_active()
        raise
    opener = build_opener(ProxyHandler({}), NoRedirect())
    # Cloudflare rejects the default Python user-agent on Pocket ID (error 1010).
    opener.addheaders = [("User-Agent", "mashu-healthcheck/1.0")]
    report.group("Public HTTPS")
    for label, url in [
        ("git.maxice8.com · health", "https://git.maxice8.com/api/healthz"),
        (
            "id.maxice8.com · OpenID configuration",
            "https://id.maxice8.com/.well-known/openid-configuration",
        ),
        ("share.mashu.maxice8.com · frontend", "https://share.mashu.maxice8.com/"),
        ("share.mashu.maxice8.com · API", "https://share.mashu.maxice8.com/api/health"),
    ]:
        with report.step(label, child=True), opener.open(url, timeout=10) as response:
            assert response.status == 200, (url, response.status)
            if url.endswith("/api/health"):
                assert response.read(4096).strip() == b"OK", (
                    "Share API health did not reach the backend"
                )
    report.group("Authentication")
    with report.step("Pomerium · login redirect", child=True):
        check_redirect(
            opener,
            "https://pomerium.maxice8.com/",
            ("https", "pomerium.maxice8.com", "/.pomerium/"),
        )
        check_redirect(
            opener,
            "https://pomerium.maxice8.com/.pomerium/",
            ("https", "id.maxice8.com", "/authorize"),
        )
    for label, host in [
        ("Argus", "argus"),
        ("ArchiSteamFarm", "asf"),
        ("Backrest", "backrest"),
        ("Netdata", "netdata"),
        ("Syncthing", "syncthing"),
    ]:
        with report.step(label + " · login required", child=True):
            check_redirect(
                opener,
                f"https://{host}.mashu.maxice8.com/",
                ("https", "pomerium.maxice8.com", "/.pomerium/sign_in"),
            )
    if probe_git:
        report.group("Git SSH")
        with report.step("Port 23 · repository refs accessible", child=True):
            result = subprocess.run(
                [
                    "git",
                    "ls-remote",
                    "--exit-code",
                    "ssh://git@git.maxice8.com:23/max/ansible.git",
                    "HEAD",
                ],
                env=os.environ
                | {
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_SSH_COMMAND": shlex.join(["ssh", *SSH_OPTIONS]),
                },
                text=True,
                capture_output=True,
                check=True,
                timeout=20,
            )
            assert any(
                re.fullmatch(r"[0-9a-f]{40,64}\tHEAD", line)
                for line in result.stdout.splitlines()
            ), "No repository HEAD received over Git SSH"


def check_stability(target_host, options=(), report=None):
    report = report or Checklist()
    report.group("Stability")
    state_script = HEALTH + "\nprint(json.dumps(service_state()))"
    with report.step("Readiness maintained · 15 seconds", child=True):
        before = json.loads(ssh(target_host, options, state_script, privileged=True))
        started = time.monotonic()
        quiet = Checklist(io.StringIO())
        for sample in range(1, 4):
            time.sleep(max(0, started + sample * 5 - time.monotonic()))
            check_health(
                target_host, options, report=quiet, probe_runner=False, probe_git=False
            )
    with report.step("No new automatic service restarts", child=True):
        after = json.loads(ssh(target_host, options, state_script, privileged=True))
        changed = sorted(
            unit
            for unit in before.keys() | after.keys()
            if before.get(unit) != after.get(unit)
        )
        assert not changed, (
            "Services restarted during the stability window: " + ", ".join(changed)
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-host", default=TAILSCALE_HOST)
    parser.add_argument("--tailscale-host", default=TAILSCALE_HOST)
    parser.add_argument("--recovery-host", default=RECOVERY_HOST)
    parser.add_argument("--ssh-option", action="append", default=[])
    args = parser.parse_args()
    check_access(
        args.target_host, args.tailscale_host, args.recovery_host, args.ssh_option
    )
    check_storage(args.target_host, args.ssh_option)
    check_health(args.target_host, args.ssh_option)
    check_stability(args.target_host, args.ssh_option)


if __name__ == "__main__":
    main()
