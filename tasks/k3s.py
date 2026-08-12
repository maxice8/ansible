import io
from ipaddress import IPv6Address
from urllib.parse import quote

from pyinfra import host
from pyinfra.facts.hardware import Ipv4Addrs, Ipv6Addrs
from pyinfra.facts.server import Command
from pyinfra.operations import apt, files, server, systemd

k3s = host.data.k3s
K3S_INSTALLER_URL = (
    "https://raw.githubusercontent.com/k3s-io/k3s/"
    f"{quote(k3s['version'], safe='')}/install.sh"
)

primary_interface = host.get_fact(
    Command,
    command=(
        "ip -o -4 route show default | "
        "awk 'NR == 1 {for (i = 1; i <= NF; i++) "
        'if ($i == "dev") {print $(i + 1); exit}}\''
    ),
)
ipv4_addresses = host.get_fact(Ipv4Addrs)
ipv6_addresses = host.get_fact(Ipv6Addrs)

try:
    primary_ipv4 = ipv4_addresses[primary_interface][0]
    primary_ipv6 = next(
        address
        for address in ipv6_addresses[primary_interface]
        if IPv6Address(address).is_global
    )
except (KeyError, StopIteration):
    raise RuntimeError("Cannot discover the primary IPv4 and IPv6 addresses")

apt.packages(
    name="Install the K3s installer dependencies",
    packages=["ca-certificates", "curl"],
)

files.directory(
    name="Create the K3s configuration directory",
    path="/etc/rancher/k3s",
    user="root",
    group="root",
    mode="0700",
)

files.directory(
    name="Create the K3s kubelet configuration directory",
    path="/var/lib/rancher/k3s/agent/etc/kubelet.conf.d",
    user="root",
    group="root",
    mode="0700",
    recursive=True,
)

kubelet_config_changed = files.put(
    name="Configure K3s image garbage collection",
    src=io.StringIO(
        """apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
imageGCHighThresholdPercent: 60
imageGCLowThresholdPercent: 50
imageMaximumGCAge: 24h
"""
    ),
    dest="/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/10-image-gc.conf",
    user="root",
    group="root",
    mode="0600",
).changed

psa_config_changed = files.put(
    name="Configure K3s Pod Security admission",
    src=io.StringIO(
        """apiVersion: apiserver.config.k8s.io/v1
kind: AdmissionConfiguration
plugins:
  - name: PodSecurity
    configuration:
      apiVersion: pod-security.admission.config.k8s.io/v1
      kind: PodSecurityConfiguration
      defaults:
        enforce: restricted
        enforce-version: v1.36
        audit: restricted
        audit-version: v1.36
        warn: restricted
        warn-version: v1.36
      exemptions:
        usernames: []
        runtimeClasses: []
        namespaces:
          - calico-apiserver
          - calico-system
          - cattle-alerting
          - cattle-capi-system
          - cattle-csp-adapter-system
          - cattle-elemental-system
          - cattle-epinio-system
          - cattle-externalip-system
          - cattle-fleet-local-system
          - cattle-fleet-system
          - cattle-gatekeeper-system
          - cattle-global-data
          - cattle-global-nt
          - cattle-impersonation-system
          - cattle-istio
          - cattle-istio-system
          - cattle-logging
          - cattle-logging-system
          - cattle-monitoring-system
          - cattle-neuvector-system
          - cattle-prometheus
          - cattle-provisioning-capi-system
          - cattle-resources-system
          - cattle-sriov-system
          - cattle-system
          - cattle-turtles-system
          - cattle-ui-plugin-system
          - cattle-windows-gmsa-system
          - cert-manager
          - cis-operator-system
          - compliance-operator-system
          - fleet-default
          - fleet-local
          - istio-system
          - kube-node-lease
          - kube-public
          - kube-system
          - longhorn-system
          - rancher-alerting-drivers
          - rancher-compliance-system
          - security-scan
          - sr-operator-system
          - tigera-operator
          - traefik
"""
    ),
    dest="/etc/rancher/k3s/psa.yaml",
    user="root",
    group="root",
    mode="0600",
).changed

k3s_config_changed = files.put(
    name="Deploy the K3s server configuration",
    src=io.StringIO(
        f'''node-name: "{host.name}"
node-ip: "{primary_ipv4},{primary_ipv6}"
tls-san:
  - "{host.name}"
cluster-cidr: "10.42.0.0/16,fd42:10:42::/56"
service-cidr: "10.43.0.0/16,fd42:10:43::/112"
flannel-ipv6-masq: true
secrets-encryption: true
write-kubeconfig-mode: "0600"
kube-apiserver-arg:
  - "admission-control-config-file=/etc/rancher/k3s/psa.yaml"
  - "service-account-extend-token-expiration=false"
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
    sha256sum=k3s["installer_sha256"],
    user="root",
    group="root",
    mode="0755",
)

installed_version = host.get_fact(
    Command,
    command="k3s --version 2>/dev/null | awk 'NR == 1 {print $3}'",
)
k3s_install_changed = installed_version != k3s["version"]
k3s_unit_reload_required = (
    host.get_fact(
        Command,
        command=(
            "systemctl show k3s.service --property=NeedDaemonReload "
            "--value 2>/dev/null || true"
        ),
    )
    == "yes"
)

if k3s_install_changed:
    install_command = (
        f"INSTALL_K3S_VERSION='{k3s['version']}' "
        "INSTALL_K3S_EXEC=server "
        "INSTALL_K3S_SKIP_START=true "
        "/usr/local/src/install-k3s.sh"
    )
    server.shell(
        name=f"Install K3s {k3s['version']}",
        commands=[install_command],
    )

systemd.service(
    name="Enable the K3s server",
    service="k3s.service",
    running=True,
    enabled=True,
    restarted=(
        k3s_config_changed
        or kubelet_config_changed
        or psa_config_changed
        or k3s_install_changed
    ),
    daemon_reload=k3s_install_changed or k3s_unit_reload_required,
)
