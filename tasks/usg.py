import io
import json

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd

pro_status_raw = host.get_fact(
    Command,
    command="pro status --format=json",
)

try:
    pro_status = json.loads(pro_status_raw)
except (TypeError, json.JSONDecodeError) as error:
    raise RuntimeError("Cannot read the Ubuntu Pro status") from error

if not pro_status.get("attached"):
    raise RuntimeError(
        "Ubuntu Pro is not attached. Run 'sudo pro attach' on Mashu, then rerun Pyinfra."
    )

usg_status = next(
    (
        service.get("status")
        for service in pro_status.get("services", [])
        if service.get("name") == "usg"
    ),
    None,
)

usg_repository_changed = False
if usg_status != "enabled":
    usg_repository_changed = server.shell(
        name="Enable the Ubuntu Security Guide repository",
        commands=["pro enable usg"],
    ).changed

usg_package_known = (
    host.get_fact(
        Command,
        command=(
            "apt-cache show usg >/dev/null 2>&1 && printf present || printf absent"
        ),
    )
    == "present"
)

apt.packages(
    name="Install the Ubuntu Security Guide",
    packages=["usg"],
    update=usg_repository_changed or not usg_package_known,
)

files.put(
    name="Deploy the Ubuntu CIS audit script",
    src=io.StringIO(
        r"""#!/bin/sh
set -eu

/usr/sbin/usg audit cis_level1_server
/usr/bin/find /var/lib/usg -maxdepth 1 -type f \
  \( -name '*.html' -o -name '*.xml' \) \
  -mtime +90 -delete
"""
    ),
    dest="/usr/local/sbin/usg-audit",
    user="root",
    group="root",
    mode="0755",
)

audit_service_changed = files.put(
    name="Deploy the Ubuntu CIS audit service",
    src=io.StringIO(
        """[Unit]
Description=Audit Ubuntu CIS Level 1 Server compliance

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/usg-audit
Nice=10
IOSchedulingClass=idle
UMask=0077
TimeoutStartSec=2h
"""
    ),
    dest="/etc/systemd/system/usg-audit.service",
    user="root",
    group="root",
    mode="0644",
).changed

audit_timer_changed = files.put(
    name="Deploy the daily Ubuntu CIS audit timer",
    src=io.StringIO(
        """[Unit]
Description=Run the Ubuntu CIS audit each day

[Timer]
OnCalendar=*-*-* 00:00:00
Persistent=true
AccuracySec=1s
Unit=usg-audit.service

[Install]
WantedBy=timers.target
"""
    ),
    dest="/etc/systemd/system/usg-audit.timer",
    user="root",
    group="root",
    mode="0644",
).changed

systemd.service(
    name="Enable the daily Ubuntu CIS audit",
    service="usg-audit.timer",
    running=True,
    enabled=True,
    restarted=audit_timer_changed,
    daemon_reload=audit_service_changed or audit_timer_changed,
)
