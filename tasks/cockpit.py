import io

from pyinfra import host
from pyinfra.operations import files, systemd

config_changed = files.put(
    name="Configure Cockpit Origins and Proxy Headers",
    src=io.StringIO(
        f"""[WebService]
Origins = https://cockpit.{host.name}.{host.data.domain_name} wss://cockpit.{host.name}.{host.data.domain_name}
ProtocolHeader = X-Forwarded-Proto
"""
    ),
    dest="/etc/cockpit/cockpit.conf",
    user="root",
    group="root",
    mode="0644",
).changed

files.directory(
    name="Ensure cockpit.socket drop-in directory exists",
    path="/etc/systemd/system/cockpit.socket.d",
    user="root",
    group="root",
    mode="0755",
)

socket_changed = files.put(
    name="Restrict Cockpit to listen only on localhost",
    src=io.StringIO(
        """[Socket]
ListenStream=
ListenStream=127.0.0.1:9090
"""
    ),
    dest="/etc/systemd/system/cockpit.socket.d/listen.conf",
    user="root",
    group="root",
    mode="0644",
).changed

if config_changed or socket_changed:
    systemd.service(name="Restart Cockpit", service="cockpit", restarted=True)

systemd.service(
    name="Ensure Cockpit is started and enabled",
    service="cockpit.socket",
    running=True,
    enabled=True,
    daemon_reload=socket_changed,
)
