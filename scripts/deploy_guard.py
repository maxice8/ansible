"""Validate access settings and restore the previous profile after a failed deploy."""

import fcntl
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path("/run/mashu-deploy")
ROOT = Path("/nix/var/nix/gcroots/mashu-deploy-rollback")
ETC = Path("/etc")
UNIT = "mashu-deploy-rollback"
CURRENT = Path("/nix/var/nix/profiles/system-manager-profiles/system-manager")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)


def entries(profile):
    return json.loads((Path(profile) / "etcFiles/etcFiles.json").read_text())["entries"]


def source(files, name):
    entry = files[name]
    if not entry["enable"]:
        raise RuntimeError(f"Required access configuration is disabled: {name}")
    return Path(entry["source"]) / entry["target"]


def firewall_binary(files):
    unit = source(files, "systemd/system") / "homelab-firewall.service"
    match = re.search(
        r"^ExecStart=(/nix/store/[^ ]+/bin/nft) -f /etc/nftables.conf$",
        unit.read_text(),
        re.MULTILINE,
    )
    if not match:
        raise RuntimeError("Unsupported host firewall command")
    return match[1]


def check_firewall(text):
    """Reject host input policies that do not have a direct SSH allowance."""
    match = re.search(r"chain input\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
    if not match:
        raise RuntimeError("Missing host input chain")
    rules = [line.split("#", 1)[0].strip() for line in match[1].splitlines()]
    for rule in rules:
        if re.fullmatch(r"tcp dport (?:22|\{[\d, ]*\b22\b[\d, ]*\}) accept", rule):
            return
        if re.search(r"\b(drop|reject|jump|goto|vmap)\b", rule) and rule not in (
            "type filter hook input priority -10; policy drop;",
            "ct state invalid drop",
        ):
            raise RuntimeError(f"Cannot prove SSH allowance before rule: {rule}")
    raise RuntimeError("Missing unconditional TCP port 22 allowance")


def preflight(profile):
    print("GROUP\tValidate candidate", flush=True)
    print("CHECK\tHost firewall", flush=True)
    files = entries(profile)
    # shortcut: recovery restores this one managed SSH file; review added SSH files.
    if {name for name in files if name.startswith("ssh/")} != {
        "ssh/sshd_config.d/10-homelab.conf"
    }:
        raise RuntimeError("Review new managed SSH files before deployment")
    firewall = source(files, "nftables.conf")
    check_firewall(firewall.read_text())
    run(firewall_binary(files), "--check", "--file", str(firewall))
    print("PASS\tHost firewall", flush=True)
    print("CHECK\tSSH configuration", flush=True)
    with tempfile.TemporaryDirectory(prefix="mashu-ssh-") as directory:
        staged = Path(directory) / "ssh"
        shutil.copytree("/etc/ssh", staged, symlinks=False)
        for name in files:
            if name.startswith("ssh/"):
                target = staged / name.removeprefix("ssh/")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source(files, name), target)
        # A private mount namespace lets sshd read candidate Include paths.
        script = """import subprocess,sys
subprocess.run(['mount','--bind',sys.argv[1],'/etc/ssh'],check=True)
subprocess.run(['/usr/sbin/sshd','-t'],check=True)
r=subprocess.run(['/usr/sbin/sshd','-T','-C','user=ubuntu,host=localhost,addr=127.0.0.1'],check=True,text=True,capture_output=True)
v=dict(line.split(' ',1) for line in r.stdout.splitlines())
assert v['pubkeyauthentication']=='yes', 'Public-key login disabled'
assert v['authenticationmethods'] in ('any','publickey'), 'Unsupported SSH authentication requirement'
assert v.get('allowusers','ubuntu')=='ubuntu', 'Unexpected AllowUsers policy'
assert not v.get('denyusers') and not v.get('denygroups') and not v.get('allowgroups'), 'Review SSH user/group restrictions'
assert '22' in v['port'].split(), 'SSH port 22 disabled'
assert v['addressfamily']=='any', 'Both SSH address families are required'
listeners=[line.split(' ',1)[1] for line in r.stdout.splitlines() if line.startswith('listenaddress ')]
assert '0.0.0.0:22' in listeners and '[::]:22' in listeners, 'Public SSH listeners are required'
"""
        run(
            "unshare",
            "--mount",
            "--propagation",
            "private",
            "/usr/bin/python3",
            "-c",
            script,
            str(staged),
        )
    print("PASS\tSSH configuration", flush=True)
    print("CHECK\tActivation assertions", flush=True)
    run(str(Path(profile) / "bin/preActivationAssertions"))
    print("PASS\tActivation assertions", flush=True)


def main(action, profile=None):
    with open("/run/mashu-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "arm":
            if STATE.exists() or ROOT.exists():
                raise RuntimeError("A previous deployment guard needs review")
            preflight(profile)
            print("GROUP\tRollback", flush=True)
            print("CHECK\tPrevious profile retained", flush=True)
            previous = CURRENT.resolve(strict=True)
            if not (previous / "bin/activate").is_file():
                raise RuntimeError("No previous profile is available for rollback")
            STATE.mkdir(mode=0o700)
            ROOT.symlink_to(previous)
            (STATE / "candidate").write_text(profile)
            (STATE / "guard.py").write_text(Path(__file__).read_text())
            assert ROOT.resolve(strict=True) == previous, (
                "Previous profile GC root is invalid"
            )
            print("PASS\tPrevious profile retained", flush=True)
            print("CHECK\tTimer armed · 30 minutes", flush=True)
            run(
                "systemd-run",
                "--collect",
                "--unit=" + UNIT,
                "--on-active=30m",
                "--timer-property=AccuracySec=1s",
                "/usr/bin/python3",
                str(STATE / "guard.py"),
                "rollback",
            )
            status = run(
                "systemctl",
                "show",
                UNIT + ".timer",
                "--property=ActiveState",
                "--property=SubState",
                capture_output=True,
            ).stdout
            status = dict(line.split("=", 1) for line in status.splitlines())
            assert status == {"ActiveState": "active", "SubState": "waiting"}, (
                "Rollback timer is not waiting"
            )
            print("PASS\tTimer armed · 30 minutes", flush=True)
            print("CHECK\tFuture trigger confirmed", flush=True)
            timer_path = (
                "/org/freedesktop/systemd1/unit/"
                + UNIT.replace("-", "_2d")
                + "_2etimer"
            )
            trigger = run(
                "busctl",
                "get-property",
                "org.freedesktop.systemd1",
                timer_path,
                "org.freedesktop.systemd1.Timer",
                "NextElapseUSecMonotonic",
                capture_output=True,
            ).stdout.split()
            assert len(trigger) == 2 and trigger[0] == "t", (
                "Invalid rollback timer trigger"
            )
            remaining = int(trigger[1]) / 1000000 - time.monotonic()
            assert 0 < remaining <= 1801, (
                "Rollback trigger is not within the next 30 minutes"
            )
            print("PASS\tFuture trigger confirmed", flush=True)
        elif action == "disarm":
            if (STATE / "rollback-started").exists():
                raise RuntimeError("Rollback has started; inspect the host")
            if (STATE / "candidate").read_text() != profile:
                raise RuntimeError("Deployment guard belongs to another profile")
            if CURRENT.resolve() != Path(profile):
                raise RuntimeError("Candidate profile is no longer active")
            print("GROUP\tRollback", flush=True)
            print("CHECK\tTimer disarmed", flush=True)
            run("systemctl", "stop", UNIT + ".timer")
            status = run(
                "systemctl",
                "show",
                UNIT + ".timer",
                "--property=ActiveState",
                "--value",
                capture_output=True,
            ).stdout.strip()
            assert status == "inactive", "Rollback timer is still active"
            print("PASS\tTimer disarmed", flush=True)
            print("CHECK\tRecovery state cleared", flush=True)
            shutil.rmtree(STATE)
            assert not STATE.exists(), "Rollback recovery state remains"
            print("PASS\tRecovery state cleared", flush=True)
            print("CHECK\tPrevious profile GC root removed", flush=True)
            ROOT.unlink()
            assert not ROOT.is_symlink() and not ROOT.exists(), (
                "Rollback GC root remains"
            )
            print("PASS\tPrevious profile GC root removed", flush=True)
        elif action == "clear":
            for unit in (UNIT + ".timer", UNIT + ".service"):
                status = run(
                    "systemctl",
                    "show",
                    unit,
                    "--property=ActiveState",
                    "--value",
                    capture_output=True,
                ).stdout.strip()
                if status not in ("inactive", "failed"):
                    raise RuntimeError(f"Rollback unit is still active: {unit}")
            if not STATE.exists() and not ROOT.is_symlink():
                print("No rollback guard to clear", flush=True)
                return
            if not (STATE / "rollback-started").exists():
                raise RuntimeError("Rollback has not started; retain the guard")
            if CURRENT.resolve(strict=True) != ROOT.resolve(strict=True):
                raise RuntimeError("Previous profile is not active; inspect the host")
            ROOT.unlink()
            shutil.rmtree(STATE)
            print("Reviewed rollback guard cleared", flush=True)
        elif action == "rollback":
            if not ROOT.exists():
                return
            (STATE / "rollback-started").touch()
            previous = ROOT.resolve()
            files = entries(previous)
            # Restore recovery access before assertions or service activation.
            for name in ["ssh/sshd_config.d/10-homelab.conf", "nftables.conf"]:
                target = ETC / name
                temporary = target.with_name(target.name + ".rollback")
                temporary.symlink_to(source(files, name))
                temporary.replace(target)
            run(firewall_binary(files), "-f", "/etc/nftables.conf")
            run("/usr/sbin/sshd", "-t")
            run("systemctl", "reload", "ssh.service")
            for operation in ["register-profile", "activate"]:
                run(str(previous / "bin" / operation))
            print(
                "Previous profile restored; deployment guard retained for review",
                flush=True,
            )
        else:
            raise ValueError(action)


if __name__ == "__main__":
    main(*sys.argv[1:])
