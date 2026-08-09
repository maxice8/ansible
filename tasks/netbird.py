import io

from pyinfra.operations import files, server, systemd

cil = files.put(
    name="Upload NetBird SELinux CIL policy",
    src=io.StringIO(
        "(type netbird_t)\n(allow netbird_t ssh_port_t (tcp_socket (name_bind)))\n"
    ),
    dest="/etc/selinux/netbird-ssh.cil",
)

if cil.changed:
    server.shell(
        name="Install NetBird SELinux CIL policy",
        commands=["semodule -i /etc/selinux/netbird-ssh.cil"],
    )

# NetBird UDP GRO Optimization (Carried over from Tailscale setup)
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
