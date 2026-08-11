import io
import re
from pathlib import Path

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import files, server

release_url = host.get_fact(
    Command,
    command=(
        "curl -fsSL --connect-timeout 10 --max-time 30 -o /dev/null "
        "-w '%{url_effective}' "
        "https://github.com/argoproj/argo-cd/releases/latest"
    ),
)
argocd_version = release_url.rsplit("/", maxsplit=1)[-1]
if not re.fullmatch(r"v\d+\.\d+\.\d+", argocd_version):
    raise RuntimeError("Cannot resolve the latest stable Argo CD version")

manifest_url = (
    "https://raw.githubusercontent.com/argoproj/argo-cd/"
    f"{argocd_version}/manifests/install.yaml"
)
manifest_sha256 = host.get_fact(
    Command,
    command=(
        f"curl -fsSL --connect-timeout 10 --max-time 30 '{manifest_url}' "
        "| sha256sum | cut -d' ' -f1"
    ),
)
if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
    raise RuntimeError("Cannot verify the latest stable Argo CD manifest")

files.download(
    name=f"Download the Argo CD {argocd_version} manifest",
    src=manifest_url,
    dest="/usr/local/src/argocd-install.yaml",
    sha256sum=manifest_sha256,
    user="root",
    group="root",
    mode="0644",
)

namespace_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl get namespace argocd >/dev/null 2>&1 "
        "&& printf present || printf absent"
    ),
)
if namespace_state != "present":
    server.shell(
        name="Create the Argo CD namespace",
        commands=["k3s kubectl create namespace argocd"],
    )

installed_image = host.get_fact(
    Command,
    command=(
        "k3s kubectl get deployment argocd-server -n argocd "
        "-o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null "
        "|| true"
    ),
)
expected_image = f"quay.io/argoproj/argocd:{argocd_version}"
workload_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl get deployment "
        "argocd-applicationset-controller argocd-dex-server "
        "argocd-notifications-controller argocd-redis argocd-repo-server "
        "argocd-server -n argocd >/dev/null 2>&1 "
        "&& k3s kubectl get statefulset argocd-application-controller "
        "-n argocd >/dev/null 2>&1 "
        "&& printf present || printf absent"
    ),
)
argocd_install_changed = (
    installed_image != expected_image or workload_state != "present"
)

if argocd_install_changed:
    server.shell(
        name=f"Install Argo CD {argocd_version}",
        commands=[
            (
                "k3s kubectl apply --server-side --force-conflicts "
                "-n argocd -f /usr/local/src/argocd-install.yaml"
            ),
            (
                "k3s kubectl wait --for=condition=Available deployment --all "
                "-n argocd --timeout=300s"
            ),
            (
                "k3s kubectl rollout status "
                "statefulset/argocd-application-controller "
                "-n argocd --timeout=300s"
            ),
        ],
    )

root_application_changed = files.put(
    name="Deploy the Mashu root application",
    src=io.StringIO(
        f'''apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: mashu
  namespace: argocd
spec:
  project: default
  source:
    repoURL: "{host.data.argocd_repository_url}"
    targetRevision: master
    path: kubernetes/clusters/mashu
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated:
      enabled: true
      prune: true
      selfHeal: true
      allowEmpty: false
    syncOptions:
      - PruneLast=true
      - ServerSideApply=true
'''
    ),
    dest="/usr/local/src/argocd-root-application.yaml",
    user="root",
    group="root",
    mode="0644",
).changed

root_application_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl get application mashu -n argocd >/dev/null 2>&1 "
        "&& printf present || printf absent"
    ),
)
if root_application_changed or root_application_state != "present":
    server.shell(
        name="Apply the Mashu root application",
        commands=["k3s kubectl apply -f /usr/local/src/argocd-root-application.yaml"],
    )

age_identity_source = Path(".age-key.txt")
if not age_identity_source.is_file():
    raise RuntimeError("Argo CD requires .age-key.txt to bootstrap SOPS")

files.directory(
    name="Create the SOPS age identity directory",
    path="/etc/sops/age",
    user="root",
    group="root",
    mode="0700",
)
age_identity_changed = files.put(
    name="Install the SOPS age identity",
    src=str(age_identity_source),
    dest="/etc/sops/age/keys.txt",
    user="root",
    group="root",
    mode="0600",
).changed

sops_namespace_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl get namespace sops-secrets-operator >/dev/null 2>&1 "
        "&& printf present || printf absent"
    ),
)
if sops_namespace_state != "present":
    server.shell(
        name="Create the SOPS operator namespace",
        commands=["k3s kubectl create namespace sops-secrets-operator"],
    )

age_secret_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl get secret sops-age-identity "
        "-n sops-secrets-operator >/dev/null 2>&1 "
        "&& printf present || printf absent"
    ),
)
if age_identity_changed or age_secret_state != "present":
    server.shell(
        name="Apply the SOPS age identity Secret",
        commands=[
            (
                "k3s kubectl create secret generic sops-age-identity "
                "-n sops-secrets-operator "
                "--from-file=keys.txt=/etc/sops/age/keys.txt "
                "--dry-run=client -o yaml | k3s kubectl apply -f -"
            )
        ],
    )
