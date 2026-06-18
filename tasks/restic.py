# tasks/restic.py
import io

from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.operations import files, server, systemd

from utils import deploy_quadlet, ensure_secret

# 1. Restic Config & SSH Keys
files.directory(
    name="Ensure Restic config directory exists",
    path="/etc/restic",
    user="root",
    group="root",
    mode="0755",
)
files.directory(
    name="Ensure Restic SSH directory exists securely",
    path="/etc/restic/ssh",
    user="root",
    group="root",
    mode="0700",
)

ssh_config = f"Host {host.data.get('restic_ssh_hostname', '')}\n  Port 23\n  IdentityFile /root/.ssh/restic_key\n  IdentitiesOnly yes\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n"
files.put(
    name="Create native SSH Config",
    src=io.StringIO(ssh_config),
    dest="/etc/restic/ssh/config",
    user="root",
    group="root",
    mode="0600",
)

# SSH Key Generation
if not host.get_fact(File, path="/etc/restic/ssh/restic_key"):
    server.shell(
        name="Generate backup-rsync SSH key",
        commands=[
            f"ssh-keygen -t ed25519 -b 4096 -N '' -f /etc/restic/ssh/restic_key -C 'root@{host.name}'"
        ],
    )

# Hetzner Key Installation
if (
    not host.get_fact(File, path="/etc/restic/ssh/.key_installed")
    and host.data.get("restic_ssh_hostname")
    and host.data.get("restic_ssh_password")
):
    server.shell(
        name="Install SSH key via temporary container",
        commands=[f"""
            podman run --rm --network host --security-opt label=disable \\
            -v /etc/restic/ssh:/mnt/ssh:ro -e SSHPASS="{host.data.restic_ssh_password}" \\
            docker.io/library/alpine:latest sh -c \\
            "apk add --no-cache sshpass openssh-client && \\
             cat /mnt/ssh/restic_key.pub | \\
             sshpass -e ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -p 23 \\
             '{host.data.restic_ssh_username}@{host.data.restic_ssh_hostname}' install-ssh-key || true" && \\
            touch /etc/restic/ssh/.key_installed
        """],
    )

ensure_secret(
    "restic_repository_passphrase", host.data.get("restic_repository_passphrase", "")
)

# 2. Quadlets
net_c = deploy_quadlet(
    "backrest.network",
    "[Unit]\nDescription=Isolated IPv4 Network for backrest\n\n[Network]",
)
data_c = deploy_quadlet("backrest-data.volume", "[Volume]")
cache_c = deploy_quadlet("backrest-cache.volume", "[Volume]")

cont_c = deploy_quadlet(
    "backrest.container",
    f"""
[Unit]
Description=Backrest (Restic Web UI)

[Container]
Image=ghcr.io/garethgeorge/backrest:latest
AutoUpdate=registry
ContainerName=backrest
Network=backrest.network
PublishPort=127.0.0.1:{host.data.get('backrest_port', 9898)}:9898

SecurityLabelDisable=true
Volume=backrest-data.volume:/data:Z
Volume=backrest-cache.volume:/cache:Z
Volume=/etc/restic/ssh:/root/.ssh:ro,Z
Volume=/var/lib/containers/storage/volumes:/source/volumes:ro
Volume=/etc:/source/etc:ro

Environment=BACKREST_DATA=/data
Environment=BACKREST_CONFIG=/data/config.json
Environment=XDG_CACHE_HOME=/cache

NoNewPrivileges=true
DropCapability=all
AddCapability=DAC_READ_SEARCH
AddCapability=NET_RAW
ReadOnly=true
Tmpfs=/tmp

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = net_c or data_c or cache_c or cont_c
if changes:
    systemd.daemon_reload(name="Reload systemd for backrest")

systemd.service(
    name="Ensure Backrest service is started",
    service="backrest.service",
    running=True,
    restarted=changes,
)
