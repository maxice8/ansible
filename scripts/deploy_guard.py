"""Validate access settings and restore the previous profile after a failed deploy."""

import fcntl
import json
import re
import shutil
import subprocess
import sys
import tempfile
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
    files = entries(profile)
    # shortcut: recovery restores this one managed SSH file; review added SSH files.
    if {name for name in files if name.startswith("ssh/")} != {
        "ssh/sshd_config.d/10-homelab.conf"
    }:
        raise RuntimeError("Review new managed SSH files before deployment")
    firewall = source(files, "nftables.conf")
    check_firewall(firewall.read_text())
    run(firewall_binary(files), "--check", "--file", str(firewall))
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
    run(str(Path(profile) / "bin/preActivationAssertions"))
    print("PASS candidate SSH, host firewall and activation assertions", flush=True)


def main(action, profile=None):
    with open("/run/mashu-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "arm":
            if STATE.exists() or ROOT.exists():
                raise RuntimeError("A previous deployment guard needs review")
            preflight(profile)
            previous = CURRENT.resolve(strict=True)
            if not (previous / "bin/activate").is_file():
                raise RuntimeError("No previous profile is available for rollback")
            STATE.mkdir(mode=0o700)
            ROOT.symlink_to(previous)
            (STATE / "candidate").write_text(profile)
            (STATE / "guard.py").write_text(Path(__file__).read_text())
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
            print("Rollback armed for 30 minutes", flush=True)
        elif action == "disarm":
            if (STATE / "rollback-started").exists():
                raise RuntimeError("Rollback has started; inspect the host")
            if (STATE / "candidate").read_text() != profile:
                raise RuntimeError("Deployment guard belongs to another profile")
            if CURRENT.resolve() != Path(profile):
                raise RuntimeError("Candidate profile is no longer active")
            run("systemctl", "stop", UNIT + ".timer")
            ROOT.unlink()
            shutil.rmtree(STATE)
            print("Rollback disarmed", flush=True)
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
