import io
import json
import shlex

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.facts.systemd import SystemdStatus
from pyinfra.operations import files, server, systemd

from helpers.system_extensions import REGISTRY_DATA_KEY

sysext_service = "systemd-sysext.service"
registered_extensions = host.data.get(REGISTRY_DATA_KEY, {})
registered_names = tuple(sorted(registered_extensions))

sysext_service_was_active = host.get_fact(
    SystemdStatus,
    services=[sysext_service],
).get(sysext_service, False)

# Facts describe state before operations run and determine whether to refresh.
sysext_status_json = host.get_fact(
    Command,
    command=(
        "systemd-sysext status --json=short --no-pager 2>/dev/null || printf '[]'"
    ),
)
try:
    sysext_status = json.loads(sysext_status_json)
except (TypeError, json.JSONDecodeError):
    sysext_status = []

active_usr_extensions = {
    extension
    for hierarchy in sysext_status
    if hierarchy.get("hierarchy") == "/usr"
    for extension in hierarchy.get("extensions", [])
}
missing_extensions = set(registered_names).difference(active_usr_extensions)

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

extension_payload_changed = any(
    extension["changed"] for extension in registered_extensions.values()
)
sysext_refresh_required = (
    extension_payload_changed
    or bool(missing_extensions)
    or usr_write_through_changed
    or sysext_mutability_changed
)

systemd.service(
    name="Enable system extension activation",
    service=sysext_service,
    running=True,
    enabled=True,
    reloaded=sysext_refresh_required and sysext_service_was_active,
)

extensions_applied = sysext_refresh_required or not sysext_service_was_active

if registered_names and extensions_applied:
    # Run remotely after refresh; Pyinfra facts still contain pre-refresh state.
    validation_script = """import json
import sys

status = json.load(sys.stdin)
active_extensions = next(
    (
        set(hierarchy.get("extensions", ()))
        for hierarchy in status
        if hierarchy.get("hierarchy") == "/usr"
    ),
    set(),
)
missing_extensions = sorted(set(sys.argv[1:]) - active_extensions)
if missing_extensions:
    raise SystemExit(
        "Missing active system extensions: " + ", ".join(missing_extensions)
    )
"""
    expected_extensions = " ".join(map(shlex.quote, registered_names))
    server.shell(
        name="Validate registered system extensions",
        commands=[
            (
                "systemd-sysext status --json=short --no-pager | "
                f"python3 -c {shlex.quote(validation_script)} "
                f"{expected_extensions}"
            ),
        ],
    )

write_routing_changed = (
    usr_write_through_changed
    or etc_write_through_changed
    or sysext_mutability_changed
    or confext_mutability_changed
)
if write_routing_changed or not sysext_service_was_active:
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

# Calling these now declares their operations after refresh and validation.
after_refresh_callbacks = []
for extension_name, extension in registered_extensions.items():
    extension_applied = (
        extension["changed"]
        or extension_name in missing_extensions
        or not sysext_service_was_active
    )
    if not extension_applied:
        continue
    callback = extension["after_refresh"]
    if callback is not None and callback not in after_refresh_callbacks:
        after_refresh_callbacks.append(callback)

for callback in after_refresh_callbacks:
    callback()
