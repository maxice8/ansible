import io

from pyinfra.operations import files, systemd

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
    daemon_reload=gro_changed,
)
