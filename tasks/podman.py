import io

from pyinfra.operations import files, server, systemd

server.user(
    name="Create 'containers' user for UserNS auto mapping",
    user="containers",
    system=True,
    shell="/sbin/nologin",
    create_home=False,
)

files.line(
    name="Allocate massive subuid range",
    path="/etc/subuid",
    line="containers:1000000:1073741824",
)
files.line(
    name="Allocate massive subgid range",
    path="/etc/subgid",
    line="containers:1000000:1073741824",
)

files.put(
    name="Create podman-system-prune service",
    src=io.StringIO(
        """[Unit]
Description=Run Podman system prune

[Service]
Type=oneshot
ExecStart=/usr/bin/podman system prune -af
"""
    ),
    dest="/etc/systemd/system/podman-system-prune.service",
    user="root",
    group="root",
    mode="0644",
)

timer_changed = files.put(
    name="Create podman-system-prune timer",
    src=io.StringIO(
        """[Unit]
Description=Run Podman system prune daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
"""
    ),
    dest="/etc/systemd/system/podman-system-prune.timer",
    user="root",
    group="root",
    mode="0644",
).changed

if timer_changed:
    systemd.daemon_reload(name="Reload systemd for podman-system-prune")

systemd.service(
    name="Enable podman-system-prune timer",
    service="podman-system-prune.timer",
    running=True,
    enabled=True,
)
systemd.service(
    name="Enable Podman Auto-Update Timer",
    service="podman-auto-update.timer",
    running=True,
    enabled=True,
)
