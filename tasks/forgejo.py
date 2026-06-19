# tasks/forgejo.py
from pyinfra import host
from pyinfra.facts.server import Users
from pyinfra.operations import systemd

from utils import apply_sysusers, deploy_quadlet

# 1. Declaratively create the user via systemd-sysusers helper
apply_sysusers("forgejo", 'u forgejo - "Forgejo Daemon" /data -')

# Fetch dynamic IDs
forgejo_user = host.get_fact(Users).get("forgejo", {})
f_uid = forgejo_user.get("uid", "forgejo")
f_gid = forgejo_user.get("gid", "forgejo")

# 2. Quadlets
net_changed = deploy_quadlet(
    "forgejo.network",
    """[Unit]
Description=Isolated Dual-Stack Network for Forgejo

[Network]
IPv6=true
""",
)

vol_changed = deploy_quadlet(
    "forgejo-data.volume",
    f"""[Volume]
User={f_uid}
Group={f_gid}
""",
)

container_changed = deploy_quadlet(
    "forgejo.container",
    f"""[Unit]
Description=Forgejo Server
After=network-online.target

[Container]
Image=codeberg.org/forgejo/forgejo:15-rootless
AutoUpdate=registry
ContainerName=forgejo

Network=forgejo.network
PublishPort=127.0.0.1:{host.data.forgejo_port}:3000
PublishPort=22:{host.data.forgejo_ssh_port}

User={f_uid}:{f_gid}
Environment=USER_UID={f_uid}
Environment=USER_GID={f_gid}
Environment=USER=forgejo

Environment=FORGEJO__service__ENABLE_BASIC_AUTHENTICATION=false
Environment=FORGEJO__service__SHOW_REGISTRATION_BUTTON=false
Environment=FORGEJO__openid__ENABLE_OPENID_SIGNIN=false
Environment=FORGEJO__openid__ENABLE_OPENID_SIGNUP=false
Environment=FORGEJO__service__DISABLE_REGISTRATION=false
Environment=FORGEJO__service__ALLOW_ONLY_EXTERNAL_REGISTRATION=true
Environment=FORGEJO__service_0x2E__REQUIRE_SIGNIN_VIEW=false
Environment=FORGEJO__service__REQUIRE_SIGNIN_VIEW=false
Environment=FORGEJO__server__DOMAIN=git.{host.data.domain_name}
Environment=FORGEJO__server__ROOT_URL=https://git.{host.data.domain_name}
Environment=FORGEJO__server__SSH_DOMAIN=git.{host.data.domain_name}
Environment=SSH_LISTEN_PORT={host.data.forgejo_ssh_port}
Environment=FORGEJO__server__SSH_PORT=22
Environment=FORGEJO__server__START_SSH_SERVER=true
Environment=FORGEJO__server__BUILTIN_SSH_SERVER_USER=git

Volume=forgejo-data.volume:/var/lib/gitea

NoNewPrivileges=true
DropCapability=all
ReadOnly=true
Tmpfs=/tmp

HealthCmd=CMD-SHELL curl -fkLsS -m 2 http://127.0.0.1:3000/api/healthz > /dev/null || exit 1
HealthInterval=30s
HealthTimeout=10s
HealthRetries=3

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = net_changed or vol_changed or container_changed
systemd.service(
    name="Ensure Forgejo service is started",
    service="forgejo.service",
    running=True,
    restarted=changes,
    daemon_reload=changes,
)
