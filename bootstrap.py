"""Prepare Ubuntu Nix, UID mapping and unattended updates; never deploy applications."""

import io
import re

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd

deployment_user = host.data.ssh_user
if not isinstance(deployment_user, str) or not re.fullmatch(
    r"[a-z_][a-z0-9_-]*", deployment_user
):
    raise ValueError("Set ssh_user to the existing Ubuntu deployment account")

release = host.get_fact(
    Command, command='. /etc/os-release && printf "%s:%s" "$ID" "$VERSION_ID"'
)
if release != "ubuntu:26.04":
    raise ValueError("The bootstrap requires Ubuntu 26.04")

if not host.get_fact(Command, command="command -v nix || true"):
    apt.packages(
        name="Install Ubuntu's multi-user Nix",
        packages=["ca-certificates", "nix-bin", "nix-setup-systemd"],
        update=True,
    )
else:
    packages = host.get_fact(
        Command,
        command="dpkg-query -W -f='${Status}\\n' nix-bin nix-setup-systemd 2>/dev/null || true",
    )
    if packages.splitlines() != ["install ok installed", "install ok installed"]:
        raise ValueError(
            "Existing Nix must use Ubuntu's nix-bin and nix-setup-systemd packages"
        )

# Rootless containers need Ubuntu's audited setuid UID/GID mapping helpers.
apt.packages(
    name="Install Ubuntu host support",
    packages=["uidmap", "unattended-upgrades"],
)

server.user(
    name="Allow the deployment administrator to access Ubuntu's Nix socket",
    user=deployment_user,
    groups=["nix-users"],
    append=True,
    ensure_home=False,
)

settings = files.put(
    name="Configure only Nix deployment features and administrator trust",
    src=io.StringIO(
        "extra-experimental-features = nix-command flakes\n"
        f"extra-trusted-users = {deployment_user}\n"
    ),
    dest="/etc/nix/homelab.conf",
    mode="0644",
    user="root",
    group="root",
)
include = files.line(
    name="Include the deployment settings without replacing Ubuntu's nix.conf",
    path="/etc/nix/nix.conf",
    line="!include /etc/nix/homelab.conf",
)
systemd.service(
    name="Run Ubuntu's Nix daemon",
    service="nix-daemon.service",
    running=True,
    enabled=True,
    restarted=settings.changed or include.changed,
)
