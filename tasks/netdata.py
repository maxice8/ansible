# tasks/netdata.py
import io

from pyinfra import host
from pyinfra.operations import files, systemd

from utils import apply_tmpfiles, deploy_quadlet

# 1. Enable Podman Socket
systemd.service(
    name="Ensure Podman socket is enabled (for container metrics)",
    service="podman.socket",
    running=True,
    enabled=True,
)

# 2. Tmpfiles
apply_tmpfiles("netdata", "d /etc/netdata 0755 root root -")

# 3. Configurations
conf_changed = files.put(
    name="Restrict Netdata web UI to localhost",
    src=io.StringIO("[web]\n    bind to = 127.0.0.1\n"),
    dest="/etc/netdata/netdata.conf",
    user="root",
    group="root",
    mode="0644",
).changed

alarm_changed = files.put(
    name="Create health_alarm_notify.conf on host",
    src=io.StringIO(
        f'SEND_DISCORD="YES"\nDISCORD_WEBHOOK_URL="{host.data.netdata_discord_alarm_webhook_url}"\nDEFAULT_RECIPIENT_DISCORD="netdata-alerts"\n'
    ),
    dest="/etc/netdata/health_alarm_notify.conf",
    user="root",
    group="root",
    mode="0644",
).changed

# 4. Quadlets
lib_vol_changed = deploy_quadlet("netdata-lib.volume", "[Volume]")
cache_vol_changed = deploy_quadlet("netdata-cache.volume", "[Volume]")

container_changed = deploy_quadlet(
    "netdata.container",
    """[Unit]
Description=Netdata Host Monitoring

[Container]
Image=docker.io/netdata/netdata:latest
ContainerName=netdata
Network=host
PodmanArgs=--pid=host --userns=host
SecurityLabelDisable=true

AddCapability=SYS_PTRACE
AddCapability=SYS_ADMIN

Volume=netdata-lib.volume:/var/lib/netdata
Volume=netdata-cache.volume:/var/cache/netdata
Volume=/etc/passwd:/host/etc/passwd:ro
Volume=/etc/group:/host/etc/group:ro
Volume=/proc:/host/proc:ro
Volume=/sys:/host/sys:ro
Volume=/etc/os-release:/host/etc/os-release:ro
Volume=/var/log:/host/var/log:ro
Volume=/run/podman/podman.sock:/var/run/docker.sock:ro
Volume=/etc/netdata/health_alarm_notify.conf:/etc/netdata/health_alarm_notify.conf:ro,z

HealthCmd=CMD-SHELL curl -fkLsS -m 2 127.0.0.1:19999/api/v1/info > /dev/null || exit 1
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

quadlet_changes = lib_vol_changed or cache_vol_changed or container_changed
if quadlet_changes:
    systemd.daemon_reload(name="Reload systemd for netdata")

systemd.service(
    name="Ensure Netdata service is started",
    service="netdata.service",
    running=True,
    restarted=(quadlet_changes or conf_changed or alarm_changed),
)

# 5. Optional Heartbeat
heartbeat_url = host.data.get("heartbeat_netdata", "")
if heartbeat_url:
    files.put(
        name="Deploy netdata-heartbeat.service",
        src=io.StringIO(
            f'[Unit]\nDescription=Netdata Heartbeat\n[Service]\nType=oneshot\nExecStart=/bin/sh -c \'/usr/bin/podman inspect --format "{{{{ .State.Health.Status }}}}" netdata | /usr/bin/grep -q healthy && /usr/bin/curl -fsS -m 5 --retry 3 "{heartbeat_url}" > /dev/null || true\'\n'
        ),
        dest="/etc/systemd/system/netdata-heartbeat.service",
        user="root",
        group="root",
        mode="0644",
    )
    hb_timer_changed = files.put(
        name="Deploy netdata-heartbeat.timer",
        src=io.StringIO(
            "[Unit]\nDescription=Netdata Heartbeat Timer\n[Timer]\nOnCalendar=*:0/5\nPersistent=true\n[Install]\nWantedBy=timers.target\n"
        ),
        dest="/etc/systemd/system/netdata-heartbeat.timer",
        user="root",
        group="root",
        mode="0644",
    ).changed

    if hb_timer_changed:
        systemd.daemon_reload(name="Reload systemd for netdata heartbeat")

    systemd.service(
        name="Ensure Netdata Heartbeat Timer is started",
        service="netdata-heartbeat.timer",
        running=True,
        enabled=True,
    )
