from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.operations import files, systemd

from utils import deploy_quadlet

config_directory = "/etc/netbird-server"
config_path = f"{config_directory}/config.yaml"
dashboard_env_path = f"{config_directory}/dashboard.env"

files.directory(
    name="Ensure NetBird server configuration directory exists",
    path=config_directory,
    user="root",
    group="root",
    mode="0700",
)

volume_changed = deploy_quadlet(
    "netbird-data.volume",
    "[Volume]\nVolumeName=netbird-data",
)

network_changed = deploy_quadlet(
    "netbird-server.network",
    "[Network]\nNetworkName=netbird-server",
)

server_changed = deploy_quadlet(
    "netbird-server.container",
    f"""
[Unit]
Description=NetBird Control Plane
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/netbirdio/netbird-server:latest
AutoUpdate=registry
ContainerName=netbird-server
Network=netbird-server.network
PublishPort=127.0.0.1:{host.data.netbird_server_port}:80
PublishPort=3478:3478/udp
Volume=netbird-data.volume:/var/lib/netbird:Z
Volume={config_path}:/etc/netbird/config.yaml:ro,Z
Exec=--config /etc/netbird/config.yaml

NoNewPrivileges=true

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

dashboard_changed = deploy_quadlet(
    "netbird-dashboard.container",
    f"""
[Unit]
Description=NetBird Dashboard
After=network-online.target
Wants=network-online.target

[Container]
Image=docker.io/netbirdio/dashboard:latest
AutoUpdate=registry
ContainerName=netbird-dashboard
Network=netbird-server.network
PublishPort=127.0.0.1:{host.data.netbird_dashboard_port}:80
EnvironmentFile={dashboard_env_path}

NoNewPrivileges=true

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

quadlets_changed = (
    volume_changed or network_changed or server_changed or dashboard_changed
)

if quadlets_changed:
    systemd.daemon_reload(name="Reload systemd for NetBird Quadlets")

if host.get_fact(File, path=config_path) and host.get_fact(
    File, path=dashboard_env_path
):
    systemd.service(
        name="Ensure NetBird server is started",
        service="netbird-server.service",
        running=True,
        restarted=server_changed,
    )

    systemd.service(
        name="Ensure NetBird dashboard is started",
        service="netbird-dashboard.service",
        running=True,
        restarted=dashboard_changed,
    )
else:
    host.noop(
        "NetBird services will remain stopped until their configuration is migrated"
    )
