# tasks/tailscale.py
import io

from pyinfra.operations import files, server, systemd

sysctl_file = files.put(
    name="Deploy Tailscale sysctl optimizations",
    src=io.StringIO("net.ipv4.ip_forward=1\nnet.ipv6.conf.all.forwarding=1\n"),
    dest="/etc/sysctl.d/99-tailscale.conf",
    user="root",
    group="root",
    mode="0644",
)

if sysctl_file.changed:
    server.shell(
        name="Apply Tailscale sysctl optimizations",
        commands=["sysctl -p /etc/sysctl.d/99-tailscale.conf"],
    )

gro_file = files.put(
    name="Deploy Tailscale UDP GRO optimization service",
    src=io.StringIO(
        "[Unit]\nDescription=Optimize Tailscale UDP GRO forwarding\nWants=network-online.target\nAfter=network-online.target\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/bin/sh -c 'NETDEV=$(ip -o route get 8.8.8.8 | cut -f 5 -d \" \"); /usr/sbin/ethtool -K $NETDEV rx-udp-gro-forwarding on rx-gro-list off'\n\n[Install]\nWantedBy=multi-user.target\n"
    ),
    dest="/etc/systemd/system/tailscale-gro.service",
    user="root",
    group="root",
    mode="0644",
)

systemd.service(
    name="Enable and start Tailscale GRO optimization service",
    service="tailscale-gro.service",
    running=True,
    enabled=True,
    daemon_reload=gro_file.changed,
)
