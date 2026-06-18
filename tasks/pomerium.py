# tasks/pomerium.py
import io

from pyinfra import host
from pyinfra.operations import files, systemd

from utils import deploy_quadlet, ensure_secret

files.directory(
    name="Ensure Pomerium config directory exists",
    path="/etc/pomerium",
    user="root",
    group="root",
    mode="0755",
)

# 1. Secrets
ensure_secret("pomerium_client_secret", host.data.get("pomerium_client_secret", ""))
ensure_secret("pomerium_cookie_secret", host.data.get("pomerium_cookie_secret", ""))

# 2. Dynamic Route Configuration
domain = host.data.domain_name
svcs = host.data.configured_services

routes = [
    f"""  - name: "Cockpit"
    description: "Fedora CoreOS System Administration"
    from: https://cockpit.{host.name}.{domain}
    to: http://127.0.0.1:9090
    pass_identity_headers: true
    policy:
      - allow:
          or:
            - authenticated_user: true"""
]

if "netdata" in svcs:
    routes.append(
        f'  - name: "Netdata"\n    description: "System Metrics"\n    from: https://netdata.{host.name}.{domain}\n    to: http://127.0.0.1:19999\n    policy:\n      - allow:\n          or:\n            - authenticated_user: true'
    )
if "syncthing" in svcs:
    routes.append(
        f'  - name: "Syncthing"\n    description: "P2P Files"\n    from: https://syncthing.{host.name}.{domain}\n    to: http://127.0.0.1:8384\n    policy:\n      - allow:\n          or:\n            - authenticated_user: true'
    )
if "asf" in svcs:
    routes.append(
        f'  - name: "ArchiSteamFarm"\n    description: "Steam Accounts"\n    from: https://asf.{host.name}.{domain}\n    to: http://127.0.0.1:{host.data.asf_port}\n    policy:\n      - allow:\n          or:\n            - authenticated_user: true'
    )
if "restic" in svcs:
    routes.append(
        f'  - name: "Backrest"\n    description: "Restic UI"\n    from: https://backrest.{host.name}.{domain}\n    to: http://127.0.0.1:{host.data.backrest_port}\n    policy:\n      - allow:\n          or:\n            - authenticated_user: true'
    )

config_yaml = (
    f"""insecure_server: true
address: ":{host.data.pomerium_port}"
idp_provider: "oidc"
idp_provider_url: "https://id.{domain}"
authenticate_service_url: "https://pomerium.{domain}"

routes:
"""
    + "\n".join(routes)
    + "\n"
)

config_changed = files.put(
    name="Template Pomerium route configuration",
    src=io.StringIO(config_yaml),
    dest="/etc/pomerium/config.yaml",
    user="root",
    group="root",
    mode="0600",
).changed

# 3. Quadlet
quadlet_changed = deploy_quadlet(
    "pomerium.container",
    f"""
[Unit]
Description=Pomerium Identity-Aware Proxy
After=network-online.target

[Container]
Image=docker.io/pomerium/pomerium:latest
AutoUpdate=registry
ContainerName=pomerium
Network=host
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

if quadlet_changed:
    systemd.daemon_reload(name="Reload systemd for pomerium")

systemd.service(
    name="Ensure Pomerium service is started",
    service="pomerium.service",
    running=True,
    restarted=(quadlet_changed or config_changed),
)
