import io

from pyinfra.operations import files, server

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

sysctl_values = {
    "net.ipv4.ip_forward": 1,
    "net.ipv6.conf.all.forwarding": 1,
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
