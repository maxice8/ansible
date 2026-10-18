#!/usr/bin/env python3
"""Build Mashu's final Nix configuration locally and deploy its store closure over SSH."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.vm import DEFAULT_DIRECTORY, NixVM

ROOT = Path(__file__).resolve().parent
UNITS = [
    "tailscaled",
    "traefik",
    "pomerium",
    "pocket-id",
    "syncthing",
    "forgejo",
    "argus",
    "archisteamfarm",
    "pingvin-share",
    "netdata",
    "forgejo-runner",
    "runner-engine",
    "backrest",
]
# System Manager can return success despite a failed service start. Check actual readiness.
READINESS = (
    """import subprocess, urllib.request
units = """
    + repr(UNITS)
    + """
subprocess.run(['systemctl', 'is-active', *units], check=True)
for port, path in [(9080, '/ping'), (28080, '/readyz'), (1411, '/.well-known/openid-configuration'),
                   (8384, '/'), (3000, '/api/healthz'), (8081, '/api/v1/healthcheck'),
                   (1242, '/'), (3001, '/'), (19999, '/api/v1/info'), (9898, '/')]:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
        assert response.status == 200, (port, response.status)
print('All native units and ten application health endpoints passed')
"""
)


def snapshot(destination: Path) -> None:
    """Copy public deployment inputs only; ignored workstation identities never enter Nix."""
    for name in ["flake.nix", "flake.lock", "bootstrap.py", "deploy.py"]:
        source = ROOT / name
        if source.is_symlink():
            raise RuntimeError(f"refusing symlinked deployment input: {source}")
        shutil.copy2(source, destination / name)
    for directory in ["hosts", "services", "pkgs", "secrets", "tests"]:
        for source in (ROOT / directory).rglob("*"):
            if source.is_symlink():
                raise RuntimeError(f"refusing symlinked deployment input: {source}")
            if not source.is_file():
                continue
            if directory == "secrets":
                include = source.name.endswith(".sops.yaml")
            else:
                include = (
                    source.suffix in {".nix", ".nft", ".py"}
                    and "__pycache__" not in source.parts
                )
            if include:
                target = destination / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    helper = destination / "scripts/configure_tailscale.py"
    helper.parent.mkdir()
    source = ROOT / "scripts/configure_tailscale.py"
    if source.is_symlink():
        raise RuntimeError("refusing symlinked Tailscale helper")
    shutil.copy2(source, helper)


def build(source: Path, output: str, builders: str, vm: NixVM | None = None) -> str:
    """Let Nix resolve caches before deciding whether an ARM builder is necessary."""
    target = f"path:{source}#{output}"
    command = ["sudo", "-n", "nix", "build", "--no-link"]
    if builders == "auto":
        builders = ""
        if needs_arm_builder(source, output):
            if vm is None:
                raise RuntimeError("An ARM VM session is required for these builds")
            print("Uncached ARM build jobs need the local NixOS VM", flush=True)
            prepare_vm(source, vm)
            builders = vm.builder()
    elif builders == "none":
        builders = ""
    return subprocess.check_output(
        command + ["--print-out-paths", "--builders", builders, target],
        text=True,
    ).strip()


def needs_arm_builder(source: Path, output: str) -> bool:
    """Inspect only Nix's pending jobs after its configured caches were checked."""
    plan = subprocess.run(
        [
            "sudo",
            "-n",
            "nix",
            "build",
            "--no-link",
            "--builders",
            "",
            "--dry-run",
            "--json",
            "--log-format",
            "raw",
            f"path:{source}#{output}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    # Dry-run JSON lists root outputs, while the raw log lists pending transitive
    # derivations. Fail visibly if Nix changes this format rather than guessing.
    pending = re.findall(r"^  (/nix/store/[^\s]+\.drv)$", plan.stderr, re.MULTILINE)
    if "will be built" in plan.stderr and not pending:
        raise RuntimeError(
            "Unsupported Nix dry-run format; cannot identify pending builders"
        )
    if not pending:
        return False
    graph = json.loads(
        subprocess.check_output(
            ["sudo", "-n", "nix", "derivation", "show", *pending], text=True
        )
    )
    graph = graph.get("derivations", graph)
    return any(derivation["system"] == "aarch64-linux" for derivation in graph.values())


def prepare_vm(source: Path, vm: NixVM) -> None:
    """Use a retained image to rebuild itself when its declarative inputs change."""
    vm.acquire()
    image_link = vm.directory / "image"
    # A previously rooted image breaks the bootstrap cycle for future image updates.
    builders = "none"
    if needs_arm_builder(source, "vm-image"):
        if not image_link.exists():
            raise RuntimeError(
                "First VM image needs bootstrapping: run make vm-image builders='<ARM builder specification>' or restore its binary cache"
            )
        vm.prepare(str(image_link.resolve()))
        builders = vm.builder()
    image = build(source, "vm-image", builders)
    subprocess.run(
        [
            "sudo",
            "-n",
            "nix-store",
            "--add-root",
            str(image_link),
            "--indirect",
            "--realise",
            image,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    vm.prepare(image)


def acceptance(source: Path, profile: str, vm: NixVM, *, force: bool = False) -> None:
    """Reuse successful shared-base checks only for identical inputs and the VM image."""
    digest = hashlib.sha256(profile.encode())
    for path in sorted(source.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(source)).encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    key = digest.hexdigest()
    record = vm.directory / "base-acceptance.json"
    if (
        not force
        and record.is_file()
        and json.loads(record.read_text()).get("key") == key
    ):
        print(
            "Shared-base VM acceptance already passed for these exact inputs",
            flush=True,
        )
        return
    tools = build(source, "vm-tools", "none")
    prepare_vm(source, vm)
    cli = build(source, "system-manager", "none")
    # The existing destructive fixture refuses any work directory outside /tmp.
    work = Path(tempfile.mkdtemp(prefix="mashu-vm-test-"))
    (work / "vm").symlink_to(vm.directory, target_is_directory=True)
    environment = vm.environment | {
        "PATH": cli + "/bin:" + tools + "/bin:" + vm.environment["PATH"],
        "PYTHONUNBUFFERED": "1",
    }
    print(f"Running shared-base VM acceptance; retained logs: {work}", flush=True)
    with (work / "suite.log").open("w") as log:
        result = subprocess.run(
            [sys.executable, str(source / "tests/test_base.py"), str(work)],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(f"VM acceptance failed; inspect {work / 'suite.log'}")
    temporary = record.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"key": key, "profile": profile, "suite": "shared-base", "logs": str(work)},
            indent=2,
        )
        + "\n"
    )
    temporary.replace(record)
    print(f"Shared-base VM acceptance passed; logs: {work}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "test", "deploy", "vm-image"])
    parser.add_argument("--target-host", default="mashu")
    parser.add_argument("--ssh-option", action="append", default=[])
    parser.add_argument(
        "--builders",
        default="auto",
        help="auto starts the local ARM VM on cache misses; none disables builders; otherwise an explicit SSH builder specification",
    )
    parser.add_argument(
        "--vm-dir",
        type=Path,
        default=DEFAULT_DIRECTORY,
        help="persistent local VM disk/cache directory",
    )
    parser.add_argument(
        "--store-path",
        help="deploy a previously built/rooted profile, including for rollback",
    )
    args = parser.parse_args()
    if not re.fullmatch(
        r"[A-Za-z0-9_@.:[\]-]+", args.target_host
    ) or args.target_host.startswith("-"):
        parser.error("invalid SSH target")
    if args.store_path and not re.fullmatch(
        r"/nix/store/[0-9a-z]{32}-[A-Za-z0-9+._=-]+", args.store_path
    ):
        parser.error("--store-path must name a Nix store profile")
    if args.store_path and args.action != "deploy":
        parser.error("--store-path is only for deploy")
    registration_started = False
    try:
        with (
            NixVM(args.vm_dir) as vm,
            tempfile.TemporaryDirectory(prefix="mashu-nix-source-") as directory,
        ):
            source = Path(directory)
            snapshot(source)
            if args.action == "vm-image":
                vm.acquire()
                if args.builders == "auto":
                    prepare_vm(source, vm)
                else:
                    image = build(source, "vm-image", args.builders)
                    subprocess.run(
                        [
                            "sudo",
                            "-n",
                            "nix-store",
                            "--add-root",
                            str(vm.directory / "image"),
                            "--indirect",
                            "--realise",
                            image,
                        ],
                        check=True,
                    )
                return 0
            profile = args.store_path or build(
                source, "systemConfigs.mashu", args.builders, vm
            )
            print(f"Profile: {profile}", flush=True)
            if args.action == "build":
                return 0
            if not args.store_path:
                acceptance(source, profile, vm, force=args.action == "test")
            if args.action == "test":
                return 0
            cli = (
                Path(build(source, "system-manager", args.builders, vm))
                / "bin/system-manager"
            )
            command = [str(cli), "--target-host", args.target_host]
            command += [f"--ssh-option={option}" for option in args.ssh_option]
            registration_started = True
            for action in ["register", "activate"]:
                subprocess.run(
                    command + [action, "--store-path", profile, "--sudo"], check=True
                )
            ssh = ["ssh", "-o", "BatchMode=yes", *args.ssh_option, args.target_host]
            subprocess.run(
                ssh + ["sudo -n /usr/bin/python3 -"],
                input=READINESS,
                text=True,
                check=True,
            )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        if registration_started:
            print(
                "Inspect readiness and deploy the previous profile explicitly if needed; "
                "application data migrations are not rolled back automatically.",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
