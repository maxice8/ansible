from pyinfra import host
from pyinfra.facts.systemd import SystemdStatus
from pyinfra.operations import files, server, systemd

sysext_service = "systemd-sysext.service"
sysext_service_was_active = host.get_fact(
    SystemdStatus,
    services=[sysext_service],
).get(sysext_service, False)

coredump_sysext_changed = files.sync(
    name="Synchronize the coredump system extension",
    src="system-extensions/coredump",
    dest="/var/lib/extensions/coredump",
    user="root",
    group="root",
    mode="0644",
    dir_mode="0755",
    delete=True,
).changed

systemd.service(
    name="Enable system extension activation",
    service=sysext_service,
    running=True,
    enabled=True,
    reloaded=coredump_sysext_changed,
)

if coredump_sysext_changed or not sysext_service_was_active:
    server.shell(
        name="Validate the coredump system extension",
        commands=[
            "systemd-sysext list --no-pager | grep -Eq '^coredump[[:space:]]'",
            (
                "systemd-sysext status --no-pager | "
                "grep -Eq '^/usr[[:space:]]+coredump([[:space:]]|$)'"
            ),
            (
                "cmp --silent "
                "/var/lib/extensions/coredump/usr/lib/systemd/"
                "coredump.conf.d/10-retention.conf "
                "/usr/lib/systemd/coredump.conf.d/10-retention.conf"
            ),
        ],
    )
