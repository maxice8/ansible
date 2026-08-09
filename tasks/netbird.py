import io

from pyinfra.operations import files, systemd

gro_file = files.put(
    name="Deploy NetBird UDP GRO optimization service",
    src=io.StringIO(
        "[Unit]\nDescription=Optimize NetBird UDP GRO forwarding\nWants=network-online.target\nAfter=network-online.target netbird.service\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/bin/sh -c 'NETDEV=$(ip -o route get 8.8.8.8 | cut -f 5 -d \" \"); /usr/sbin/ethtool -K $NETDEV rx-udp-gro-forwarding on rx-gro-list off'\n\n[Install]\nWantedBy=multi-user.target\n"
    ),
    dest="/etc/systemd/system/netbird-gro.service",
    user="root",
    group="root",
    mode="0644",
)

systemd.service(
    name="Enable and start NetBird GRO optimization service",
    service="netbird-gro.service",
    running=True,
    enabled=True,
    daemon_reload=gro_file.changed,
)
