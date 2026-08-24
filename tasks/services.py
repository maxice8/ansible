import io

from pyinfra.operations import apt, files, systemd

apt.packages(
    name="Install the system core dump handler",
    packages=["systemd-coredump"],
)

files.directory(
    name="Create the journald configuration directory",
    path="/etc/systemd/journald.conf.d",
    user="root",
    group="root",
    mode="0755",
)

journald_config_changed = files.put(
    name="Configure the system journal retention",
    src=io.StringIO(
        """[Journal]
Storage=persistent
Compress=yes
SystemMaxUse=512M
SystemKeepFree=5G
SystemMaxFileSize=64M
MaxRetentionSec=7day
MaxFileSec=1day
"""
    ),
    dest="/etc/systemd/journald.conf.d/10-retention.conf",
    user="root",
    group="root",
    mode="0644",
).changed

systemd.service(
    name="Apply the system journal retention",
    service="systemd-journald.service",
    running=True,
    restarted=journald_config_changed,
)

for service in ("rpcbind.socket", "rpcbind.service"):
    systemd.service(
        name=f"Disable {service}",
        service=service,
        running=False,
        enabled=False,
    )
