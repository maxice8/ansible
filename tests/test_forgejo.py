"""Check native Forgejo hook prerequisites; run as root on the selected host."""

import os
import pwd
import subprocess
import urllib.request
from pathlib import Path


def main():
    assert os.geteuid() == 0, "Run as root on the intended deployment target"
    pid = subprocess.check_output(
        ["systemctl", "show", "forgejo.service", "-p", "MainPID", "--value"], text=True
    ).strip()
    assert int(pid) > 0, "Forgejo is not running"
    environment = dict(
        entry.split("=", 1)
        for entry in Path(f"/proc/{pid}/environ").read_text().split("\0")
        if "=" in entry
    )
    account = pwd.getpwnam("forgejo")
    result = subprocess.run(
        ["/usr/bin/env", "bash", "--version"],
        env=environment,
        user=account.pw_uid,
        group=account.pw_gid,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    unit = subprocess.check_output(
        ["systemctl", "show", "forgejo.service", "-p", "ExecStartPre"], text=True
    )
    assert "admin regenerate hooks" not in unit, "Obsolete Forgejo startup command"
    with urllib.request.urlopen(
        "http://127.0.0.1:3000/api/healthz", timeout=10
    ) as response:
        assert response.status == 200
    print("Forgejo service Bash lookup, startup commands and health passed")


if __name__ == "__main__":
    main()
