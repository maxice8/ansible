import io
import json

from pyinfra import host
from pyinfra.facts.server import Users
from pyinfra.operations import files, systemd

from utils import (
    apply_sysusers,
    apply_tmpfiles,
    deploy_quadlet,
    ensure_secret,
)

apply_sysusers("forgejo-runner", 'u forgejo-runner - "Forgejo Runner Daemon" /data -')
apply_tmpfiles("forgejo-runner", "d /etc/forgejo-runner 0755 root root -")

runner_user = host.get_fact(Users).get("forgejo-runner", {})
r_uid = runner_user.get("uid", "forgejo-runner")
r_gid = runner_user.get("gid", "forgejo-runner")

config_yaml = f"""log:
  level: info

runner:
  file: .runner
  name: "{host.name}-runner"
  capacity: 1
  envs:
  timeout: 3h
  shutdown_timeout: 3h
  fetch_interval: 2s
  labels:
    - "alpine:docker://alpine:latest"
    - "docker:docker://docker:dind"
    - "ubuntu-latest:docker://node:20-bookworm"

cache:
  enabled: true
  dir: ""

container:
  network: ""
  enable_ipv6: true
  privileged: false
  options:
  workdir_parent:
  valid_volumes:
    - '**'
  docker_host: ""
  force_pull: false

host:
  workdir_parent:
"""

daemon_json = (
    json.dumps(
        {
            "ipv6": True,
            "experimental": True,
            "ip6tables": True,
            "fixed-cidr-v6": "fd7a:115c:a1e0:1::/64",
            "default-address-pools": [
                {"base": "172.30.0.0/16", "size": 24},
                {"base": "fd7a:115c:a1e0:100::/56", "size": 64},
            ],
        },
        indent=2,
    )
    + "\n"
)

entrypoint_sh = f"""#!/bin/sh
set -e
cd /data

if [ ! -f .runner ]; then
  echo "Runner credentials not found. Attempting registration for {host.name}..."
  if [ -z "$FORGEJO_RUNNER_TOKEN" ]; then
    echo "Error: FORGEJO_RUNNER_TOKEN is not set. Cannot register."
    while : ; do sleep 3600 ; done
  fi
  forgejo-runner register --no-interactive \\
    --instance "$FORGEJO_INSTANCE_URL" \\
    --token "$FORGEJO_RUNNER_TOKEN" \\
    --name "forgejo-runner-{host.name}"
  echo "Registration successful."
else
  echo "Runner credentials found. Skipping registration."
fi

echo "Starting Forgejo Runner daemon..."
sleep 5
exec forgejo-runner daemon --config config.yml
"""

config_changed = files.put(
    name="Deploy config.yml",
    src=io.StringIO(config_yaml),
    dest="/etc/forgejo-runner/config.yml",
    user="forgejo-runner",
    group="forgejo-runner",
    mode="0644",
).changed
entrypoint_changed = files.put(
    name="Deploy entrypoint.sh",
    src=io.StringIO(entrypoint_sh),
    dest="/etc/forgejo-runner/entrypoint.sh",
    user="forgejo-runner",
    group="forgejo-runner",
    mode="0755",
).changed
daemon_changed = files.put(
    name="Deploy Docker daemon.json",
    src=io.StringIO(daemon_json),
    dest="/etc/forgejo-runner/daemon.json",
    user="root",
    group="root",
    mode="0644",
).changed

secret_changed = ensure_secret(
    "forgejo_runner_token", host.data.get("forgejo_runner_token", "")
)

net_c = deploy_quadlet(
    "forgejo-runner.network",
    """[Unit]
Description=Isolated Dual-Stack Network for forgejo-runner

[Network]
IPv6=True""",
)
dind_vol_c = deploy_quadlet("dind-data.volume", "[Volume]")
dind_c = deploy_quadlet(
    "dind.container",
    """
[Unit]
Description=Docker-in-Docker for Forgejo Runner

[Container]
Image=docker.io/library/docker:dind
AutoUpdate=registry
ContainerName=docker_dind
Network=forgejo-runner.network
PodmanArgs=--privileged
Exec=dockerd -H tcp://0.0.0.0:2375 --tls=false
Volume=dind-data.volume:/var/lib/docker
Volume=/etc/forgejo-runner/daemon.json:/etc/docker/daemon.json:ro,z

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
)

run_vol_c = deploy_quadlet(
    "forgejo-runner-data.volume",
    f"""[Volume]
User={r_uid}
Group={r_gid}""",
)
add_host = f"AddHost=git.{host.data.domain_name}:host-gateway"
if "forgejo" not in host.data.host_services:
    add_host = ""

run_c = deploy_quadlet(
    "runner.container",
    f"""
[Unit]
Description=Forgejo Runner
Requires=dind.service
After=dind.service

[Container]
Image=code.forgejo.org/forgejo/runner:13
AutoUpdate=registry
ContainerName=forgejo-runner
Network=forgejo-runner.network
HostName=forgejo-runner-{host.name}
User={r_uid}:{r_gid}

Secret=forgejo_runner_token,type=env,target=FORGEJO_RUNNER_TOKEN
Environment=DOCKER_HOST=tcp://docker_dind:2375
Environment=FORGEJO_INSTANCE_URL=https://git.{host.data.domain_name}
{add_host}
Volume=forgejo-runner-data.volume:/data:U
Volume=/etc/forgejo-runner/config.yml:/data/config.yml:ro,z
Volume=/etc/forgejo-runner/entrypoint.sh:/data/entrypoint.sh:ro,z
Volume=/etc/passwd:/etc/passwd:ro
Volume=/etc/group:/etc/group:ro

Exec=/bin/sh /data/entrypoint.sh

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

dind_changes = net_c or dind_vol_c or dind_c or daemon_changed
runner_changes = run_vol_c or run_c or daemon_changed

if dind_changes or runner_changes:
    systemd.daemon_reload(name="Reload systemd for forgejo-runner")

systemd.service(
    name="Ensure DinD service is started",
    service="dind.service",
    running=True,
    restarted=dind_changes,
)
systemd.service(
    name="Ensure Forgejo Runner service is started",
    service="runner.service",
    running=True,
    restarted=(
        net_c
        or runner_changes
        or config_changed
        or entrypoint_changed
        or secret_changed
    ),
)
