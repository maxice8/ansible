from pyinfra.operations import systemd

from utils import deploy_quadlet

net_changed = deploy_quadlet(
    "whoami.network",
    "[Unit]\nDescription=Isolated Dual-Stack Network for whoami\n\n[Network]\nIPv6=True",
)

container_changed = deploy_quadlet(
    "whoami.container",
    """
[Unit]
Description=Traefik Whoami

[Container]
Image=docker.io/traefik/whoami:latest
AutoUpdate=registry
ContainerName=whoami
Network=whoami.network
UserNS=auto
Exec=--port 8080

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
systemd.service(
    name="Ensure whoami service is started",
    service="whoami.service",
    running=True,
    restarted=changes,
    daemon_reload=changes,
)
