import io

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import files, server, systemd

K3S_INSTALLER_SHA256 = (
    "8598e002e61d658fed7b7542fc6d2c66d8da6eae69e088830105d2ee1ffb6d91"
)
K3S_INSTALLER_URL = (
    "https://raw.githubusercontent.com/k3s-io/k3s/v1.35.5%2Bk3s1/install.sh"
)

files.directory(
    name="Create the K3s configuration directory",
    path="/etc/rancher/k3s",
    user="root",
    group="root",
    mode="0700",
)

k3s_config_changed = files.put(
    name="Deploy the K3s server configuration",
    src=io.StringIO(
        f'''node-name: "{host.name}"
node-ip: "{host.data.private_ipv4},{host.data.public_ipv6}"
tls-san:
  - "{host.name}"
  - "{host.data.private_ipv4}"
  - "{host.data.public_ipv4}"
  - "{host.data.public_ipv6}"
  - "{host.data.netbird_ipv4}"
cluster-cidr: "10.42.0.0/16,fd42:10:42::/56"
service-cidr: "10.43.0.0/16,fd42:10:43::/112"
flannel-ipv6-masq: true
secrets-encryption: true
write-kubeconfig-mode: "0600"
disable:
  - traefik
cluster-init: true
'''
    ),
    dest="/etc/rancher/k3s/config.yaml",
    user="root",
    group="root",
    mode="0600",
).changed

files.directory(
    name="Create the local source directory",
    path="/usr/local/src",
    user="root",
    group="root",
    mode="0755",
)

files.download(
    name="Download the pinned K3s installer",
    src=K3S_INSTALLER_URL,
    dest="/usr/local/src/install-k3s.sh",
    sha256sum=K3S_INSTALLER_SHA256,
    user="root",
    group="root",
    mode="0755",
)

installed_version = host.get_fact(
    Command,
    command="k3s --version 2>/dev/null | awk 'NR == 1 {print $3}'",
)
k3s_install_changed = installed_version != host.data.k3s_version

if k3s_install_changed:
    install_command = (
        f"INSTALL_K3S_VERSION='{host.data.k3s_version}' "
        "INSTALL_K3S_EXEC=server "
        "INSTALL_K3S_SKIP_START=true "
        "/usr/local/src/install-k3s.sh"
    )
    server.shell(
        name=f"Install K3s {host.data.k3s_version}",
        commands=[install_command],
    )

systemd.service(
    name="Enable the K3s server",
    service="k3s.service",
    running=True,
    enabled=True,
    restarted=k3s_config_changed or k3s_install_changed,
    daemon_reload=k3s_install_changed,
)
