import io
import re

from pyinfra import host
from pyinfra.facts.files import File
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd

public_interface = host.get_fact(
    Command,
    command=(
        "ip -o -4 route show default | "
        "awk 'NR == 1 {for (i = 1; i <= NF; i++) "
        'if ($i == "dev") {print $(i + 1); exit}}\''
    ),
)
if not re.fullmatch(r"[A-Za-z0-9_.:@-]+", public_interface):
    raise RuntimeError("Cannot discover the public network interface")

apt.packages(
    name="Install nftables",
    packages=["nftables"],
)

files.directory(
    name="Create the nftables extension directory",
    path="/etc/nftables.d",
    user="root",
    group="root",
    mode="0755",
)

for rules_file in ("rules.v4", "rules.v6"):
    source_path = f"/etc/iptables/{rules_file}"
    backup_path = f"{source_path}.oracle-backup"
    if host.get_fact(File, path=source_path) and not host.get_fact(
        File,
        path=backup_path,
    ):
        server.shell(
            name=f"Back up the Oracle {rules_file} rules",
            commands=[f"cp --preserve=all {source_path} {backup_path}"],
        )

firewall_config_changed = files.put(
    name="Deploy the Mashu nftables policy",
    src=io.StringIO(
        """#!/usr/sbin/nft -f

# This file owns only the hostfilter table. K3s and NetBird own their tables.
destroy table inet hostfilter

table inet hostfilter {
    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;

        iifname "__PUBLIC_INTERFACE__" tcp dport 80 counter redirect to :8000
        iifname "__PUBLIC_INTERFACE__" tcp dport 443 counter redirect to :8443
    }

    chain output_nat {
        type nat hook output priority dstnat; policy accept;

        fib daddr type local tcp dport 80 counter redirect to :8000
        fib daddr type local tcp dport 443 counter redirect to :8443
    }

    chain input {
        type filter hook input priority -10; policy drop;

        iifname "lo" counter accept
        iifname "wt0" counter accept
        ct state established,related counter accept
        udp sport 547 udp dport 546 counter accept
        ct state invalid counter drop
        meta l4proto { icmp, ipv6-icmp } counter accept
        iifname { "cni0", "flannel.1" } counter accept
        ct original proto-dst { 80, 443 } counter accept
        tcp dport { 22, 23, 22000 } counter accept
        udp dport { 3478, 51820, 21027, 22000 } counter accept
    }

    chain forward {
        type filter hook forward priority -10; policy accept;
    }

    chain output {
        type filter hook output priority -10; policy accept;
    }
}

include "/etc/nftables.d/*.conf"
""".replace("__PUBLIC_INTERFACE__", public_interface)
    ),
    dest="/etc/nftables.conf",
    user="root",
    group="root",
    mode="0600",
).changed

if firewall_config_changed:
    server.shell(
        name="Validate the Mashu nftables policy",
        commands=["nft --check -f /etc/nftables.conf"],
    )

firewall_unit_changed = files.put(
    name="Deploy the Mashu firewall service",
    src=io.StringIO(
        """[Unit]
Description=Apply the Mashu host firewall policy
After=network-pre.target
Before=k3s.service netbird.service

[Service]
Type=oneshot
ExecStart=/usr/sbin/nft -f /etc/nftables.conf
ExecReload=/usr/sbin/nft -f /etc/nftables.conf
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
    ),
    dest="/etc/systemd/system/homelab-firewall.service",
    user="root",
    group="root",
    mode="0644",
).changed

firewall_revision = host.get_fact(
    Command,
    command=(
        "nft list table inet hostfilter 2>/dev/null | "
        "grep -F 'redirect to :8443' >/dev/null && "
        "nft list table inet hostfilter 2>/dev/null | "
        "grep -F 'udp dport { 3478, 51820, 21027, 22000 }' >/dev/null && "
        "nft list table inet hostfilter 2>/dev/null | "
        "grep -F 'udp sport 547 udp dport 546' >/dev/null && "
        "nft list table inet hostfilter 2>/dev/null | "
        "grep -F 'tcp dport { 22, 23, 22000 }' >/dev/null "
        "&& printf current || printf stale"
    ),
)
firewall_changed = (
    firewall_config_changed or firewall_unit_changed or firewall_revision != "current"
)

systemd.service(
    name="Enable the Mashu firewall policy",
    service="homelab-firewall.service",
    running=True,
    enabled=True,
    reloaded=firewall_changed,
    daemon_reload=firewall_unit_changed,
)

systemd.service(
    name="Disable the Oracle firewall loader",
    service="netfilter-persistent.service",
    running=False,
    enabled=False,
)

legacy_firewall = host.get_fact(
    Command,
    command=(
        "nft list table ip filter 2>/dev/null | "
        "grep -F InstanceServices >/dev/null && printf present || printf absent"
    ),
)
if legacy_firewall == "present":
    server.shell(
        name="Remove the live Oracle firewall table",
        commands=[
            "nft delete table ip filter",
            "nft delete table ip6 filter 2>/dev/null || true",
        ],
    )

for old_path in (
    "/etc/nftables.d/homelab.nft",
    "/usr/local/sbin/apply-homelab-firewall",
):
    files.file(
        name=f"Remove {old_path}",
        path=old_path,
        present=False,
    )
