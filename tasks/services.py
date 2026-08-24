from pyinfra.operations import apt, systemd

from helpers.system_extensions import sync_system_extension


def apply_journald_extension():
    """Reload journald after its extension is applied."""
    systemd.service(
        name="Reload journald after applying its system extension",
        service="systemd-journald.service",
        running=True,
        reloaded=True,
    )


apt.packages(
    name="Install the system core dump handler",
    packages=["systemd-coredump"],
)

sync_system_extension("coredump")
sync_system_extension(
    "journald",
    after_refresh=apply_journald_extension,
)

for service in ("rpcbind.socket", "rpcbind.service"):
    systemd.service(
        name=f"Disable {service}",
        service=service,
        running=False,
        enabled=False,
    )
