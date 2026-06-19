# tasks/pocket_id.py
from pyinfra import host
from pyinfra.operations import systemd

from utils import deploy_quadlet, ensure_secret

if not host.data.get("pocket_id_encryption_key"):
    raise ValueError("pocket_id_encryption_key is missing from host data.")

# 1. Secret
ensure_secret("pocket_id_encryption_key", host.data.pocket_id_encryption_key)

# 2. Quadlets
net_changed = deploy_quadlet(
    "pocket-id.network",
    "[Unit]\nDescription=Isolated IPv4 Network for pocket-id\n\n[Network]",
)
vol_changed = deploy_quadlet(
    "pocket-id-data.volume", "[Volume]\n# Persists the Pocket ID SQLite DB"
)

container_changed = deploy_quadlet(
    "pocket-id.container",
    f"""
[Unit]
Description=Pocket ID (OIDC Provider)
After=network-online.target

[Container]
Image=ghcr.io/pocket-id/pocket-id:v2
AutoUpdate=registry
ContainerName=pocket-id
Network=pocket-id.network
UserNS=auto
PublishPort=127.0.0.1:{host.data.pocket_id_port}:1411

Secret=pocket_id_encryption_key,type=env,target=ENCRYPTION_KEY
Environment=APP_URL=https://id.{host.data.domain_name}
Environment=TRUST_PROXY=true

Volume=pocket-id-data.volume:/app/data:U
HealthCmd=/app/pocket-id healthcheck
HealthInterval=1m30s
HealthTimeout=5s
HealthRetries=2

NoNewPrivileges=true
DropCapability=all
AddCapability=CHOWN
AddCapability=FOWNER
AddCapability=DAC_OVERRIDE
AddCapability=SETUID
AddCapability=SETGID
Tmpfs=/tmp

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = net_changed or vol_changed or container_changed
systemd.service(
    name="Ensure Pocket ID service is started",
    service="pocket-id.service",
    running=True,
    restarted=changes,
    daemon_reload=changes,
)
