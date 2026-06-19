# tasks/asf.py
import io
import json

from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.facts.server import Users
from pyinfra.operations import files, systemd

from utils import apply_sysusers, apply_tmpfiles, deploy_quadlet

# 1. Tmpfiles & Sysusers
apply_tmpfiles("asf", "d /etc/asf 0755 root root -\nd /etc/asf/config 0700 asf asf -")
apply_sysusers("asf", 'u asf - "ArchiSteamFarm Daemon" /app/config -')

# Fetch dynamic User IDs
asf_user_info = host.get_fact(Users).get("asf", {})
asf_uid = asf_user_info.get("uid", "asf")
asf_gid = asf_user_info.get("gid", "asf")

# 2. Idempotent Config Bootstrapping
asf_json = (
    json.dumps(
        {
            "CurrentCulture": "en",
            "IPCPassword": host.data.asf_ipc_password,
            "IPCPasswordFormat": 1,
            "Headless": True,
            "UpdatePeriod": 0,
        },
        indent=2,
    )
    + "\n"
)
ipc_config = (
    json.dumps({"Kestrel": {"Endpoints": {"HTTP": {"Url": "http://*:1242"}}}}, indent=4)
    + "\n"
)

json_changed = False
if not host.get_fact(File, path="/etc/asf/config/ASF.json"):
    json_changed = files.put(
        name="Deploy ASF.json",
        src=io.StringIO(asf_json),
        dest="/etc/asf/config/ASF.json",
        user="asf",
        group="asf",
        mode="0600",
    ).changed

ipc_changed = False
if not host.get_fact(File, path="/etc/asf/config/IPC.config"):
    ipc_changed = files.put(
        name="Deploy IPC.config",
        src=io.StringIO(ipc_config),
        dest="/etc/asf/config/IPC.config",
        user="asf",
        group="asf",
        mode="0600",
    ).changed

# 3. Quadlets
net_changed = deploy_quadlet(
    "asf.network", "[Unit]\nDescription=Isolated IPv4 Network for asf\n\n[Network]"
)

container_changed = deploy_quadlet(
    "asf.container",
    f"""
[Unit]
Description=ArchiSteamFarm (ASF)

[Container]
Image=docker.io/justarchi/archisteamfarm:latest
AutoUpdate=registry
ContainerName=asf

Network=asf.network
PublishPort=127.0.0.1:{host.data.asf_port}:1242

User={asf_uid}:{asf_gid}
Volume=/etc/asf/config:/app/config:U,Z

DropCapability=all
ReadOnly=true
Tmpfs=/tmp
Mount=type=tmpfs,destination=/app/logs,tmpfs-mode=0755,chown=true

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = net_changed or container_changed
systemd.service(
    name="Ensure ASF service is started",
    service="asf.service",
    running=True,
    restarted=(changes or json_changed or ipc_changed),
    daemon_reload=changes,
)
