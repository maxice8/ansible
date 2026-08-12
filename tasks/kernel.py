import io
import re

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import files, server

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

kernel_modules = ("overlay", "br_netfilter", "nf_conntrack")

files.put(
    name="Configure the K3s kernel modules",
    src=io.StringIO("\n".join(kernel_modules) + "\n"),
    dest="/etc/modules-load.d/k3s.conf",
    user="root",
    group="root",
    mode="0644",
)

for module in kernel_modules:
    server.modprobe(
        name=f"Load the {module} kernel module",
        module=module,
    )

ipv6_netplan_changed = files.put(
    name="Enable IPv6 DHCP on the public interface",
    src=io.StringIO(
        f"""network:
  version: 2
  ethernets:
    {public_interface}:
      accept-ra: true
      dhcp6: true
"""
    ),
    dest="/etc/netplan/60-public-ipv6.yaml",
    user="root",
    group="root",
    mode="0600",
).changed

if ipv6_netplan_changed:
    server.shell(
        name="Apply the public IPv6 network configuration",
        commands=["netplan generate", "netplan apply"],
    )

sysctl_values = {
    "net.ipv4.ip_forward": 1,
    "net.ipv6.conf.all.forwarding": 1,
    "net.ipv6.conf.all.accept_ra": 2,
    "net.ipv6.conf.default.accept_ra": 2,
    "net.bridge.bridge-nf-call-iptables": 1,
    "net.bridge.bridge-nf-call-ip6tables": 1,
    "fs.inotify.max_user_instances": 8192,
    "fs.inotify.max_user_watches": 524288,
}

for key, value in sysctl_values.items():
    server.sysctl(
        name=f"Set {key}",
        key=key,
        value=value,
        persist=True,
        persist_file="/etc/sysctl.d/90-k3s.conf",
    )
