# tasks/pingvin_share.py
from pyinfra import host
from pyinfra.operations import systemd
from utils import deploy_quadlet

# 1. Quadlets
net_changed = deploy_quadlet(
    "pingvin-share.network",
    "[Unit]\nDescription=Isolated IPv4 Network for Pingvin Share\n\n[Network]",
)

data_vol_changed = deploy_quadlet("pingvin-share-data.volume", "[Volume]")
img_vol_changed = deploy_quadlet("pingvin-share-images.volume", "[Volume]")

container_changed = deploy_quadlet(
    "pingvin-share.container",
    f"""
[Unit]
Description=Pingvin Share X (File Sharing)
After=network-online.target

[Container]
Image=docker.io/smp46/pingvin-share-x:latest
AutoUpdate=registry
ContainerName=pingvin-share
Network=pingvin-share.network
# Map container port 3000 to the host port
PublishPort=127.0.0.1:{host.data.get("pingvin_share_port", 3000)}:3000
Environment=TRUST_PROXY=true
Volume=pingvin-share-data.volume:/opt/app/backend/data:U
Volume=pingvin-share-images.volume:/opt/app/frontend/public/img:U
HealthCmd=CMD-SHELL curl -fkLsS -m 2 http://127.0.0.1:3000 > /dev/null || exit 1
HealthInterval=30s
HealthTimeout=5s
HealthRetries=3
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

changes = net_changed or data_vol_changed or img_vol_changed or container_changed

systemd.service(
    name="Ensure Pingvin Share service is started",
    service="pingvin-share.service",
    running=True,
    restarted=changes,
    daemon_reload=changes,
)
