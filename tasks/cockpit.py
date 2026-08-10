import io

from pyinfra import host
from pyinfra.operations import files, systemd

from inventory import POMERIUM_HOST_IPV4_GATEWAY

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
    name="Restrict Cockpit to private host addresses",
    src=io.StringIO(
        f"""[Unit]
Requires=pomerium-network.service
After=pomerium-network.service

[Socket]
ListenStream=
ListenStream={POMERIUM_HOST_IPV4_GATEWAY}:9090
"""
    ),
    dest="/etc/systemd/system/cockpit.socket.d/listen.conf",
    user="root",
    group="root",
    mode="0644",
).changed

if socket_changed:
    systemd.service(
        name="Stop Cockpit before its socket changes",
        service="cockpit",
        running=False,
    )
elif config_changed:
    systemd.service(name="Restart Cockpit", service="cockpit", restarted=True)

systemd.service(
    name="Ensure Cockpit is started and enabled",
    service="cockpit.socket",
    running=True,
    enabled=True,
    restarted=socket_changed,
    daemon_reload=socket_changed,
)
