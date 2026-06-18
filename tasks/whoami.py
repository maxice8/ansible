# tasks/whoami.py
from pyinfra import host
from pyinfra.operations import systemd

from utils import deploy_quadlet

net_changed = deploy_quadlet(
    "whoami.network",
    "[Unit]\nDescription=Isolated IPv4 Network for whoami\n\n[Network]",
)

container_changed = deploy_quadlet(
    "whoami.container",
    f"""
[Unit]
Description=Traefik Whoami

[Container]
Image=docker.io/traefik/whoami:latest
AutoUpdate=registry
ContainerName=whoami
Network=whoami.network
UserNS=auto
Exec=--port {host.data.whoami_port}
PublishPort=127.0.0.1:{host.data.whoami_port}:{host.data.whoami_port}

NoNewPrivileges=true
DropCapability=all
ReadOnly=true
Tmpfs=/tmp

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = net_changed or container_changed
if changes:
    systemd.daemon_reload(name="Reload systemd for whoami")

systemd.service(
    name="Ensure whoami service is started",
    service="whoami.service",
    running=True,
    restarted=changes,
)
