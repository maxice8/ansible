# tasks/syncthing.py
import io

from pyinfra import host
from pyinfra.facts.server import Users
from pyinfra.operations import files, systemd

from utils import apply_sysusers, deploy_quadlet

# 1. Sysusers
apply_sysusers("syncthing", 'u syncthing - "Syncthing Daemon" /var/syncthing -')

syncthing_user = host.get_fact(Users).get("syncthing", {})
st_uid = syncthing_user.get("uid", "syncthing")
st_gid = syncthing_user.get("gid", "syncthing")

# 2. Quadlets
net_changed = deploy_quadlet(
    "syncthing.network",
    """[Unit]
Description=Isolated IPv4 Network for syncthing

[Network]
""",
)

vol_changed = deploy_quadlet(
    "syncthing-data.volume",
    f"""[Volume]
User={st_uid}
Group={st_gid}
""",
)

container_changed = deploy_quadlet(
    "syncthing.container",
    f"""[Unit]
Description=Syncthing Server

[Container]
Image=docker.io/syncthing/syncthing:latest
AutoUpdate=registry
ContainerName=syncthing
HostName=syncthing
Network=syncthing.network
PublishPort=127.0.0.1:8384:8384
PublishPort=22000:22000/tcp
PublishPort=22000:22000/udp
PublishPort=21027:21027/udp

Environment=PUID={st_uid}
Environment=PGID={st_gid}
Volume=syncthing-data.volume:/var/syncthing

NoNewPrivileges=true
DropCapability=all
AddCapability=CHOWN
AddCapability=FOWNER
AddCapability=DAC_OVERRIDE
AddCapability=SETUID
AddCapability=SETGID
ReadOnly=true
Tmpfs=/tmp

HealthCmd=CMD-SHELL curl -fkLsS -m 2 127.0.0.1:8384/rest/noauth/health | grep -o --color=never OK || exit 1
HealthInterval=15s
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
    name="Ensure Syncthing service is started",
    service="syncthing.service",
    running=True,
    restarted=changes,
    daemon_reload=changes,
)

# 3. Optional Heartbeat
heartbeat_url = host.data.get("heartbeat_syncthing", "")
if heartbeat_url:
    files.put(
        name="Deploy syncthing-heartbeat.service",
        src=io.StringIO(
            f'[Unit]\nDescription=Syncthing Heartbeat\n[Service]\nType=oneshot\nExecStart=/bin/sh -c \'/usr/bin/podman inspect --format "{{{{ .State.Health.Status }}}}" syncthing | /usr/bin/grep -q healthy && /usr/bin/curl -fsS -m 5 --retry 3 "{heartbeat_url}" > /dev/null || true\'\n'
        ),
        dest="/etc/systemd/system/syncthing-heartbeat.service",
        user="root",
        group="root",
        mode="0644",
    )
    hb_timer_changed = files.put(
        name="Deploy syncthing-heartbeat.timer",
        src=io.StringIO(
            "[Unit]\nDescription=Syncthing Heartbeat Timer\n[Timer]\nOnCalendar=*:0/5\nPersistent=true\n[Install]\nWantedBy=timers.target\n"
        ),
        dest="/etc/systemd/system/syncthing-heartbeat.timer",
        user="root",
        group="root",
        mode="0644",
    ).changed

    systemd.service(
        name="Ensure Syncthing Heartbeat Timer is started",
        service="syncthing-heartbeat.timer",
        running=True,
        enabled=True,
        daemon_reload=hb_timer_changed,
    )
