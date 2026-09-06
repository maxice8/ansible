import io
import json
import os
import subprocess
from pathlib import Path

from pyinfra import host
from pyinfra.api.hiddenvalue import HiddenValue
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd

# Only initial enrollment needs the local SOPS identity. Registered hosts can
# reconcile preferences even after the auth key or local identity is removed.
backend_state = host.get_fact(
    Command,
    command=(
        "if command -v tailscale >/dev/null 2>&1 "
        "&& systemctl is-active --quiet tailscaled; then "
        "tailscale status --json | python3 -c "
        "'import json,sys; print(json.load(sys.stdin)[\"BackendState\"])'; "
        "else printf NeedsLogin; fi"
    ),
)
auth_key = ""
if backend_state in {"NeedsLogin", "NoState"}:
    root = Path(__file__).resolve().parent.parent
    environment = os.environ.copy()
    if (root / ".age-key.txt").is_file():
        environment["SOPS_AGE_KEY_FILE"] = str(root / ".age-key.txt")
    try:
        decrypted = subprocess.run(
            [
                "sops",
                "--decrypt",
                "--output-type",
                "json",
                str(root / "vars/settings.sops.yaml"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        auth_key = json.loads(decrypted.stdout)["tailscale"]["auth_key"]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        raise RuntimeError(
            "Cannot load vars/settings.sops.yaml. Restore .age-key.txt or configure "
            "your SOPS identity, then run make secret service=tailscale."
        ) from None
    if not isinstance(auth_key, str):
        raise RuntimeError("tailscale.auth_key must be a string")
    if not auth_key.strip() or auth_key == "REPLACE_WITH_TAILSCALE_AUTH_KEY":
        raise RuntimeError("Set the auth key with make secret service=tailscale first")

apt.packages(
    name="Install Tailscale dependencies",
    packages=["ca-certificates", "python3"],
)

key_changed = files.download(
    name="Install the Tailscale repository key",
    src="https://pkgs.tailscale.com/stable/ubuntu/resolute.noarmor.gpg",
    dest="/usr/share/keyrings/tailscale-archive-keyring.gpg",
    user="root",
    group="root",
    mode="0644",
).changed

repository_changed = files.put(
    name="Configure the Tailscale APT repository",
    src=io.StringIO(
        "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] "
        "https://pkgs.tailscale.com/stable/ubuntu resolute main\n"
    ),
    dest="/etc/apt/sources.list.d/tailscale.list",
    user="root",
    group="root",
    mode="0644",
).changed

apt.packages(
    name="Install the Tailscale client",
    packages=["tailscale"],
    update=key_changed or repository_changed,
)

config_changed = files.put(
    name="Configure the Tailscale daemon",
    src=io.StringIO('PORT="41641"\nFLAGS=""\n'),
    dest="/etc/default/tailscaled",
    user="root",
    group="root",
    mode="0644",
).changed

systemd.service(
    name="Enable the Tailscale client",
    service="tailscaled.service",
    running=True,
    enabled=True,
    restarted=config_changed,
)

files.put(
    name="Install the Tailscale enrollment helper",
    src="scripts/configure_tailscale.py",
    dest="/usr/local/sbin/configure-tailscale",
    user="root",
    group="root",
    mode="0700",
)

server.shell(
    name="Enroll Tailscale and configure SSH, routes, DNS, and tag:server",
    commands=["/usr/local/sbin/configure-tailscale"],
    _if=lambda: (
        host.get_fact(
            Command,
            command=(
                "if /usr/local/sbin/configure-tailscale --check >/dev/null 2>&1; "
                "then printf ready; else printf configure; fi"
            ),
        )
        != "ready"
    ),
    _env={"TS_AUTHKEY": HiddenValue(auth_key)},
)
