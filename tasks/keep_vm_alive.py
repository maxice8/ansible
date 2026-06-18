# tasks/keep_vm_alive.py
import io

from pyinfra import host
from pyinfra.operations import files, systemd

from utils import ShellFact, deploy_quadlet

files.directory(
    name="Create build directory",
    path="/etc/keep-vm-alive",
    user="root",
    group="root",
    mode="0755",
)

sh_content = f"""#!/usr/bin/env bash
HEARTBEAT_URL="{host.data.get('heartbeat_keep_vm_alive', '')}"
CPU_LOAD=25
RUN_TIME=45
SLEEP_TIME=255

send_heartbeat() {{
    if [ -n "$HEARTBEAT_URL" ]; then
        echo "Sending heartbeat..."
        curl -fsS -m 5 --retry 3 "$HEARTBEAT_URL" > /dev/null 2>&1
    fi
}}

echo "Initializing containerized keep-vm-alive..."
echo "Method: stress-ng (All Cores)"
echo "Configuration: Cycle 5m | Load $CPU_LOAD% | Active ${{RUN_TIME}}s | Sleep ${{SLEEP_TIME}}s"

while true; do
    send_heartbeat
    echo "Starting stress cycle..."
    stress-ng --cpu 0 --cpu-load $CPU_LOAD --timeout $RUN_TIME --metrics-brief
    echo "Cycle finished. Sleeping for ${{SLEEP_TIME}}s..."
    sleep $SLEEP_TIME
done
"""

containerfile_content = """FROM docker.io/library/alpine:latest
RUN apk add --no-cache bash curl stress-ng
COPY keep-vm-alive.sh /usr/local/bin/keep-vm-alive
RUN chmod +x /usr/local/bin/keep-vm-alive
CMD ["/usr/local/bin/keep-vm-alive"]
"""

sh_changed = files.put(
    name="Deploy keep-vm-alive.sh",
    src=io.StringIO(sh_content),
    dest="/etc/keep-vm-alive/keep-vm-alive.sh",
    user="root",
    group="root",
    mode="0755",
).changed
cf_changed = files.put(
    name="Deploy Containerfile",
    src=io.StringIO(containerfile_content),
    dest="/etc/keep-vm-alive/Containerfile",
    user="root",
    group="root",
    mode="0644",
).changed

build_changed = deploy_quadlet(
    "keep-vm-alive.build",
    "[Unit]\nDescription=Build keep-vm-alive container image\n\n[Build]\nImageTag=localhost/keep-vm-alive:latest\nFile=/etc/keep-vm-alive/Containerfile\nSetWorkingDirectory=/etc/keep-vm-alive\nPodmanArgs=--network=host",
)
quad_changed = deploy_quadlet(
    "keep-vm-alive.container",
    """
[Unit]
Description=Oracle Cloud Reclamation Prevention (stress-ng)

[Container]
Image=localhost/keep-vm-alive:latest
ContainerName=keep-vm-alive
AutoUpdate=local
UserNS=auto
WorkingDir=/tmp
NoNewPrivileges=true
DropCapability=all
ReadOnly=true
Tmpfs=/tmp

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

changes = build_changed or quad_changed
if changes:
    systemd.daemon_reload(name="Reload systemd for keep-vm-alive")

image_exists = host.get_fact(
    ShellFact,
    "podman image exists localhost/keep-vm-alive:latest && echo 'yes' || echo 'no'",
)

if sh_changed or cf_changed or build_changed or image_exists != "yes":
    systemd.service(
        name="Rebuild keep-vm-alive container",
        service="keep-vm-alive-build.service",
        restarted=True,
    )

systemd.service(
    name="Ensure keep-vm-alive service is started",
    service="keep-vm-alive.service",
    running=True,
    restarted=(quad_changed or sh_changed or cf_changed),
)
