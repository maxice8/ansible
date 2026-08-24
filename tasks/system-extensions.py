import io

from pyinfra import host
from pyinfra.facts.systemd import SystemdStatus
from pyinfra.operations import files, server, systemd

sysext_service = "systemd-sysext.service"
sysext_service_was_active = host.get_fact(
    SystemdStatus,
    services=[sysext_service],
).get(sysext_service, False)

# Auto mode makes only routed hierarchies mutable. These symlinks write through
# to the host trees; /opt intentionally has no mutable route.
files.directory(
    name="Create the extension write routing directory",
    path="/var/lib/extensions.mutable",
    user="root",
    group="root",
    mode="0755",
)

usr_write_through_changed = files.link(
    name="Route system extension writes to the host /usr",
    path="/var/lib/extensions.mutable/usr",
    target="/usr",
).changed

etc_write_through_changed = files.link(
    name="Route configuration extension writes to the host /etc",
    path="/var/lib/extensions.mutable/etc",
    target="/etc",
).changed

files.directory(
    name="Create the system extension configuration directory",
    path="/etc/systemd/sysext.conf.d",
    user="root",
    group="root",
    mode="0755",
)

sysext_mutability_changed = files.put(
    name="Keep selected system extension hierarchies mutable",
    src=io.StringIO(
        """[SysExt]
Mutable=auto
"""
    ),
    dest="/etc/systemd/sysext.conf.d/80-mutable.conf",
    user="root",
    group="root",
    mode="0644",
).changed

files.directory(
    name="Create the configuration extension configuration directory",
    path="/etc/systemd/confext.conf.d",
    user="root",
    group="root",
    mode="0755",
)

confext_mutability_changed = files.put(
    name="Keep selected configuration extension hierarchies mutable",
    src=io.StringIO(
        """[ConfExt]
Mutable=auto
"""
    ),
    dest="/etc/systemd/confext.conf.d/80-mutable.conf",
    user="root",
    group="root",
    mode="0644",
).changed

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

sysext_refresh_required = (
    coredump_sysext_changed or usr_write_through_changed or sysext_mutability_changed
)

systemd.service(
    name="Enable system extension activation",
    service=sysext_service,
    running=True,
    enabled=True,
    reloaded=sysext_refresh_required,
)

if sysext_refresh_required or not sysext_service_was_active:
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

if sysext_refresh_required or etc_write_through_changed or confext_mutability_changed:
    server.shell(
        name="Validate extension write routing",
        commands=[
            "readlink /var/lib/extensions.mutable/usr | grep -Fx /usr",
            "readlink /var/lib/extensions.mutable/etc | grep -Fx /etc",
            (
                "findmnt --noheadings --output OPTIONS --target /usr | "
                "tr ',' '\\n' | grep -Fx rw"
            ),
            (
                "findmnt --noheadings --output OPTIONS --target /etc | "
                "tr ',' '\\n' | grep -Fx rw"
            ),
            (
                "systemd-analyze cat-config systemd/sysext.conf | "
                "grep -Fx 'Mutable=auto'"
            ),
            (
                "systemd-analyze cat-config systemd/confext.conf | "
                "grep -Fx 'Mutable=auto'"
            ),
        ],
    )
