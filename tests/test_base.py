"""Destructive integration check, restricted to the managed NixOS ARM test VM."""

import argparse
import base64
import hashlib
import json
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

REPO = Path(__file__).resolve().parent.parent
CACHE_KEY = "niks3.numtide.com-1:DTx8wZduET09hRmMtKdQDxNNthLQETkc/yaX7M4qK0g="


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    work = args.directory.resolve()
    vm = work / "vm"
    config = vm / "ssh_config"
    if not work.is_relative_to("/tmp"):
        raise ValueError("Use a disposable /tmp directory")
    text = config.read_text()
    if "HostName 127.0.0.1\n" not in text or "User builder\n" not in text:
        raise ValueError("Refusing a target outside the disposable local VM")
    ssh = ["ssh", "-F", str(config), "vm"]
    evidence = {}

    def run(command, *, input=None, check=True, log=None):
        if log:
            print(f"RUN {log}", flush=True)
            logfile = work / f"{log}.log"
            with logfile.open("w") as output:
                result = subprocess.run(
                    command,
                    input=input,
                    text=True,
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=output,
                )
            result.stderr = logfile.read_text()
            logfile.write_text(result.stdout + result.stderr)
        else:
            result = subprocess.run(
                command, input=input, text=True, capture_output=True, check=False
            )
        if check and result.returncode:
            raise RuntimeError(
                f"{shlex.join(command)}\n{result.stdout[-2000:]}{result.stderr[-4000:]}"
            )
        return result

    def remote(command, **kwargs):
        return run(ssh + [command], **kwargs)

    def record(name, value=True):
        evidence[name] = value
        (work / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(f"PASS {name}: {value}", flush=True)

    if remote("hostname").stdout.strip() != "mashu-test":
        raise ValueError("Refusing a non-test host")
    remote('. /etc/os-release && test "$ID" = nixos')
    # A previous failed run may have left these fixtures active on the retained disk.
    # Stop while their old unit files still exist so the policy's ExecStop can run.
    remote("sudo systemctl stop homelab-probe homelab-peer-policy", check=False)
    record(
        "baseline",
        remote("uname -m; systemctl --version | head -1; cat /etc/os-release").stdout,
    )
    accounts_before = remote("getent passwd root builder; getent group wheel").stdout
    remote("nix store info")
    record("nix_provisioned_by_guest_configuration")
    passwd_before = set(remote("getent passwd").stdout.splitlines())
    groups_before = set(remote("getent group").stdout.splitlines())

    # Copy only public implementation files; this checkout also holds real secret identities.
    source = work / "source"
    source.mkdir(exist_ok=True)
    for name in (
        "flake.nix",
        "flake.lock",
        "hosts",
        "services",
        "pkgs",
        "secrets",
        "tests",
    ):
        original = REPO / name
        if original.is_dir():
            shutil.copytree(
                original,
                source / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        else:
            shutil.copy2(original, source / name)

    key = work / "fixture-age.key"
    if not key.exists():
        run(["age-keygen", "-o", str(key)])
    recipient = run(["age-keygen", "-y", str(key)]).stdout.strip()
    remote(
        "sudo install -d -m 0700 /var/lib/sops-nix; sudo sh -c 'umask 077; cat > /var/lib/sops-nix/key.txt'",
        input=key.read_text(),
    )

    port = next(
        line.split()[1]
        for line in text.splitlines()
        if line.strip().startswith("Port ")
    )
    hostkey = remote("cat /etc/ssh/ssh_host_ed25519_key.pub").stdout.strip()
    query = urlencode(
        {
            "ssh-key": str(vm / "id_ed25519"),
            "base64-ssh-public-host-key": base64.b64encode(hostkey.encode()).decode(),
        }
    )
    builder = f"ssh://builder@127.0.0.1:{port}?{query} aarch64-linux - 2 1"
    build = [
        "sudo",
        "-n",
        "nix",
        "build",
        "--no-link",
        "--print-out-paths",
        "--builders",
        builder,
        "--extra-substituters",
        "https://cache.numtide.com",
        "--extra-trusted-public-keys",
        CACHE_KEY,
    ]
    cli = [
        "system-manager",
        "--target-host",
        "vm",
        "--ssh-option=-F",
        f"--ssh-option={config}",
    ]

    def activate(path, name, *, check=True):
        run(cli + ["register", "--store-path", path, "--sudo"], log=f"{name}-register")
        return run(
            cli + ["activate", "--store-path", path, "--sudo"],
            check=check,
            log=f"{name}-activate",
        )

    def fixture(name, *, secret="fixture-one", version="one", **flags):
        plain = work / "fixture-plain.yaml"
        plain.touch(mode=0o600, exist_ok=True)
        plain.write_text(f"probe: {secret}\n")
        try:
            encrypted = run(
                [
                    "sops",
                    "--config",
                    "/dev/null",
                    "--encrypt",
                    "--age",
                    recipient,
                    str(plain),
                ]
            ).stdout
        finally:
            plain.unlink()
        secretfile = source / "tests/probe.sops.yaml"
        secretfile.write_text(encrypted)
        command = build + [
            "--impure",
            "--file",
            str(source / "tests/base-profile.nix"),
            "--argstr",
            "source",
            str(source),
            "--argstr",
            "secretFile",
            str(secretfile),
            "--argstr",
            "version",
            version,
        ]
        for flag, value in flags.items():
            command += ["--arg", flag, "true" if value else "false"]
        path = run(command, log=f"{name}-build").stdout.strip()
        record(f"build_{name}", path)
        return path

    def health():
        return json.loads(remote("curl --fail --silent http://127.0.0.1:18080/").stdout)

    def wait_health():
        for _ in range(120):
            result = remote("curl --fail --silent http://127.0.0.1:18080/", check=False)
            if result.returncode == 0:
                return json.loads(result.stdout)
            time.sleep(2)
        raise RuntimeError("Probe did not recover; inspect VM journal")

    def sandbox(name):
        remote("sudo python3 -", input=(REPO / "tests/network_control.py").read_text())
        result = json.loads(
            remote("curl --fail --silent http://127.0.0.1:18080/checks").stdout
        )
        assert result.pop("state_mode") == "0o700"
        assert all(result.values()), result
        remote(
            "sudo -u homelab-probe test ! -r /run/secrets/probe && sudo -u homelab-other test ! -r /run/secrets/probe"
        )
        record(name, result)

    # The production host now includes applications; keep base lifecycle checks isolated.
    base = fixture("base", baseOnly=True)
    record("arm_base_built", base)
    activate(base, "base")
    remote("systemctl is-active --quiet system-manager.target")
    assert (
        remote("getent passwd root builder; getent group wheel").stdout
        == accounts_before
    )
    assert remote("stat -c '%a %U %G' /var/lib/data").stdout.strip() == "711 root root"
    record("base_activation_and_accounts")

    one = fixture("one")
    activate(one, "one")
    first = wait_health()
    nft = next(
        line.removeprefix("ExecStart=").split()[0]
        for line in remote("systemctl cat homelab-peer-policy").stdout.splitlines()
        if line.startswith("ExecStart=")
    )
    if not nft.startswith("/nix/store/") or not nft.endswith("/bin/nft"):
        raise ValueError("Unexpected fixture nftables executable")
    assert first["secret_hash"] == hashlib.sha256(b"fixture-one").hexdigest()
    activate(one, "repeat")
    assert health()["pid"] == first["pid"]
    record("repeat_activation_no_restart")

    sandbox("sandbox_checks")
    limits = remote("systemctl show homelab-probe -p MemoryMax -p TasksMax").stdout
    assert "MemoryMax=134217728" in limits and "TasksMax=64" in limits
    kernel_limits = remote(
        'cg=$(systemctl show homelab-probe -p ControlGroup --value); cat "/sys/fs/cgroup$cg/memory.max" "/sys/fs/cgroup$cg/pids.max"'
    ).stdout
    assert kernel_limits.splitlines() == ["134217728", "64"]
    record("resource_limits", kernel_limits)
    before_state = remote(
        "sudo stat -c '%i %Y' /var/lib/data/homelab-probe/persistent"
    ).stdout

    two = fixture("two", version="two")
    activate(two, "two")
    second = wait_health()
    assert second["version"] == "two" and second["pid"] != first["pid"]
    record("configuration_restart")
    rotated = fixture("rotated", secret="fixture-two", version="two")
    activate(rotated, "rotated")
    third = wait_health()
    assert third["secret_hash"] == hashlib.sha256(b"fixture-two").hexdigest()
    assert third["pid"] != second["pid"]
    record("secret_rotation_restart")

    bad = fixture("assertion-failure", fail=True)
    assert activate(bad, "assertion-failure", check=False).returncode != 0
    assert health() == third
    record("failed_assertion_preserves_running_service")
    activate(one, "rollback")
    assert wait_health()["version"] == "one"
    assert health()["secret_hash"] == first["secret_hash"]
    record("previous_generation_activation")

    broken = fixture("broken-start", brokenStart=True)
    failure = activate(broken, "broken-start", check=False)
    assert (
        remote("systemctl is-failed homelab-probe", check=False).stdout.strip()
        == "failed"
    )
    record(
        "failed_start",
        {"activation_returncode": failure.returncode, "unit_state": "failed"},
    )
    activate(one, "restore-after-failed-start")
    wait_health()

    boot = remote("cat /proc/sys/kernel/random/boot_id").stdout
    remote("sudo reboot", check=False)
    for _ in range(180):
        time.sleep(3)
        check = remote("cat /proc/sys/kernel/random/boot_id", check=False)
        if check.returncode == 0 and check.stdout != boot:
            break
    else:
        raise RuntimeError("VM did not reboot")
    assert wait_health()["secret_hash"] == first["secret_hash"]
    assert (
        remote("getent passwd root builder; getent group wheel").stdout
        == accounts_before
    )
    assert passwd_before <= set(remote("getent passwd").stdout.splitlines())
    assert groups_before <= set(remote("getent group").stdout.splitlines())
    assert (
        remote("sudo stat -c '%i %Y' /var/lib/data/homelab-probe/persistent").stdout
        == before_state
    )
    record("reboot_credentials_state_accounts_ssh")
    sandbox("sandbox_checks_after_reboot")
    roots = remote(f"sudo nix-store --query --roots {shlex.quote(one)}").stdout
    assert "system-manager" in roots
    record("closure_gc_roots", roots)

    removed = fixture("removed", removed=True)
    # Stop before System Manager unlinks the unit; otherwise ExecStop is lost.
    remote("sudo systemctl stop homelab-probe.service homelab-peer-policy.service")
    assert (
        "table inet homelab_probe_test"
        not in remote(f"sudo {shlex.quote(nft)} list tables").stdout
    )
    activate(removed, "removed")
    assert remote("systemctl is-active homelab-probe", check=False).returncode != 0
    assert (
        remote("sudo stat -c '%i %Y' /var/lib/data/homelab-probe/persistent").stdout
        == before_state
    )
    record("removed_unit_stops_state_preserved")
    assert (
        "table inet homelab_probe_test"
        not in remote(f"sudo {shlex.quote(nft)} list tables").stdout
    )
    record("owned_policy_table_removed")
    activate(base, "final-base")
    activate(base, "final-base-repeat")
    assert " ERROR " not in (work / "final-base-repeat-activate.log").read_text()
    historical_roots = remote(
        f"sudo nix-store --query --roots {shlex.quote(one)}"
    ).stdout
    assert "system-manager-profiles" in historical_roots
    record("previous_generation_gc_roots", historical_roots)
    accounts = remote("getent passwd; getent group").stdout
    run(cli + ["deactivate", "--store-path", base, "--sudo"], log="deactivate-base")
    remote(
        "test ! -e /etc/homelab/base.json && test ! -e /etc/profile.d/system-manager-path.sh"
    )
    # NixOS enables socket activation; its daemon service itself is not enabled.
    remote("systemctl is-active --quiet nix-daemon.socket")
    remote("systemctl is-enabled --quiet nix-daemon.socket")
    run(["ssh", "-F", str(config), "-O", "exit", "vm"], check=False)
    remote("nix store info")
    assert remote("getent passwd; getent group").stdout == accounts
    assert (
        remote("sudo stat -c '%i %Y' /var/lib/data/homelab-probe/persistent").stdout
        == before_state
    )
    activate(base, "reinstall-base")
    assert " ERROR " not in (work / "reinstall-base-activate.log").read_text()
    record("first_install_deactivate_and_reinstall")
    record("complete")


if __name__ == "__main__":
    main()
