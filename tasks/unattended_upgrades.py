import io

from pyinfra.operations import apt, files, systemd

apt.packages(
    name="Install unattended upgrades",
    packages=["unattended-upgrades"],
)

files.put(
    name="Enable periodic unattended upgrades",
    src=io.StringIO(
        """APT::Periodic::Enable "1";
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
"""
    ),
    dest="/etc/apt/apt.conf.d/20auto-upgrades",
    user="root",
    group="root",
    mode="0644",
)

files.put(
    name="Configure unattended upgrade cleanup",
    src=io.StringIO(
        """Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
"""
    ),
    dest="/etc/apt/apt.conf.d/52unattended-upgrades-local",
    user="root",
    group="root",
    mode="0644",
)

for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
    systemd.service(
        name=f"Enable {timer}",
        service=timer,
        running=True,
        enabled=True,
    )
