from pyinfra.operations import apt, systemd

from helpers.configuration_extensions import sync_configuration_extension

apt.packages(
    name="Install unattended upgrades",
    packages=["unattended-upgrades"],
)

sync_configuration_extension("unattended-upgrades")

for timer in ("apt-daily.timer", "apt-daily-upgrade.timer"):
    systemd.service(
        name=f"Enable {timer}",
        service=timer,
        running=True,
        enabled=True,
    )
