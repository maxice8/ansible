from pyinfra import host
from pyinfra.operations import files, systemd

from inventory import POMERIUM_HOST_IPV4_GATEWAY, POMERIUM_HOST_IPV4_SUBNET
from utils import deploy_quadlet, deploy_template, ensure_secret

pomerium_network_changed = deploy_quadlet(
    "pomerium.network",
    f"""[Unit]
Description=Isolated Dual-Stack Network for Pomerium

[Network]
IPv6=True
Subnet={POMERIUM_HOST_IPV4_SUBNET}
Gateway={POMERIUM_HOST_IPV4_GATEWAY}""",
)

systemd.service(
    name="Ensure the Pomerium network exists",
    service="pomerium-network.service",
    running=True,
    daemon_reload=pomerium_network_changed,
)

files.directory(
    name="Ensure Pomerium config directory exists",
    path="/etc/pomerium",
    user="root",
    group="root",
    mode="0755",
)

client_secret_changed = ensure_secret(
    "pomerium_client_secret", host.data.get("pomerium_client_secret", "")
)
cookie_secret_changed = ensure_secret(
    "pomerium_cookie_secret", host.data.get("pomerium_cookie_secret", "")
)

config_changed = deploy_template(
    name="Template Pomerium route configuration",
    src="templates/pomerium/config.yaml.j2",
    dest="/etc/pomerium/config.yaml",
    user="root",
    group="root",
    mode="0600",
    domain=host.data.domain_name,
    host_gateway=POMERIUM_HOST_IPV4_GATEWAY,
    hostname=host.name,
    services=host.data.host_services,
)

quadlet_changed = deploy_quadlet(
    "pomerium.container",
    f"""
[Unit]
Description=Pomerium Identity-Aware Proxy
After=network-online.target
Requires=pomerium-network.service
After=pomerium-network.service

[Container]
Image=docker.io/pomerium/pomerium:latest
AutoUpdate=registry
ContainerName=pomerium
Network=pomerium.network
{"Network=syncthing.network" if "syncthing" in host.data.host_services else ""}
{"Network=asf.network" if "asf" in host.data.host_services else ""}
{"Network=backrest.network" if "restic" in host.data.host_services else ""}
Volume=/etc/pomerium/config.yaml:/pomerium/config.yaml:ro,z

Environment=IDP_CLIENT_ID={host.data.pomerium_client_id}
Secret=pomerium_client_secret,type=env,target=IDP_CLIENT_SECRET
Secret=pomerium_cookie_secret,type=env,target=COOKIE_SECRET

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

systemd.service(
    name="Ensure Pomerium service is started",
    service="pomerium.service",
    running=True,
    restarted=(
        quadlet_changed
        or config_changed
        or client_secret_changed
        or cookie_secret_changed
    ),
    daemon_reload=quadlet_changed,
)
