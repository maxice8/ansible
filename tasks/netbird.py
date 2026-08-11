import io

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, systemd

apt.packages(
    name="Install NetBird dependencies",
    packages=["ca-certificates", "curl", "ethtool"],
)

files.download(
    name="Install the NetBird repository key",
    src="https://pkgs.netbird.io/debian/public.key",
    dest="/usr/share/keyrings/netbird-archive-keyring.asc",
    user="root",
    group="root",
    mode="0644",
)

repository_changed = files.put(
    name="Configure the NetBird APT repository",
    src=io.StringIO(
        "deb [signed-by=/usr/share/keyrings/netbird-archive-keyring.asc] "
        "https://pkgs.netbird.io/debian stable main\n"
    ),
    dest="/etc/apt/sources.list.d/netbird.list",
    user="root",
    group="root",
    mode="0644",
).changed

netbird_package_known = (
    host.get_fact(
        Command,
        command=(
            "apt-cache show netbird >/dev/null 2>&1 "
            "&& printf present || printf absent"
        ),
    )
    == "present"
)

apt.packages(
    name="Install the NetBird client",
    packages=["netbird"],
    update=repository_changed or not netbird_package_known,
)

systemd.service(
    name="Enable the NetBird client",
    service="netbird.service",
    running=True,
    enabled=True,
)

gro_changed = files.put(
    name="Deploy NetBird UDP GRO optimization service",
    src=io.StringIO(
        """[Unit]
Description=Optimize NetBird UDP GRO forwarding
Wants=network-online.target
After=network-online.target netbird.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'NETDEV=$(ip -o route get 8.8.8.8 | cut -f 5 -d " "); /usr/sbin/ethtool -K $NETDEV rx-udp-gro-forwarding on rx-gro-list off'

[Install]
WantedBy=multi-user.target
"""
    ),
    dest="/etc/systemd/system/netbird-gro.service",
    user="root",
    group="root",
    mode="0644",
).changed

systemd.service(
    name="Enable and start NetBird GRO optimization service",
    service="netbird-gro.service",
    running=True,
    enabled=True,
    restarted=gro_changed,
    daemon_reload=gro_changed,
)
