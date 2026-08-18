import hashlib
import io
from pathlib import Path

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import files, server

argocd = host.data.argocd
manifest_url = (
    "https://raw.githubusercontent.com/argoproj/argo-cd/"
    f"{argocd['version']}/manifests/install.yaml"
)

files.download(
    name=f"Download the Argo CD {argocd['version']} manifest",
    src=manifest_url,
    dest="/usr/local/src/argocd-install.yaml",
    sha256sum=argocd["manifest_sha256"],
    user="root",
    group="root",
    mode="0644",
)

namespace_changed = files.put(
    name="Configure the Argo CD namespace",
    src=io.StringIO(
        """apiVersion: v1
kind: Namespace
metadata:
  name: argocd
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: v1.36
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: v1.36
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: v1.36
"""
    ),
    dest="/usr/local/src/argocd-namespace.yaml",
    user="root",
    group="root",
    mode="0644",
).changed

namespace_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl diff -f /usr/local/src/argocd-namespace.yaml >/dev/null 2>&1; "
        "case $? in 0) printf current;; *) printf drifted;; esac"
    ),
)
if namespace_changed or namespace_state != "current":
    server.shell(
        name="Apply the Argo CD namespace",
        commands=["k3s kubectl apply -f /usr/local/src/argocd-namespace.yaml"],
    )

installed_image = host.get_fact(
    Command,
    command=(
        "k3s kubectl get deployment argocd-server -n argocd "
        "-o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null "
        "|| true"
    ),
)
expected_image = f"quay.io/argoproj/argocd:{argocd['version']}"
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
        name=f"Install Argo CD {argocd['version']}",
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

server_parameters_changed = files.put(
    name="Configure the Argo CD server",
    src=io.StringIO(
        """apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
data:
  server.insecure: "true"
"""
    ),
    dest="/usr/local/src/argocd-server-parameters.yaml",
    user="root",
    group="root",
    mode="0644",
).changed

server_parameters_state = host.get_fact(
    Command,
    command=(
        "k3s kubectl diff "
        "-f /usr/local/src/argocd-server-parameters.yaml >/dev/null 2>&1; "
        "case $? in 0) printf current;; *) printf drifted;; esac"
    ),
)
if server_parameters_changed or server_parameters_state != "current":
    server.shell(
        name="Apply the Argo CD server configuration",
        commands=["k3s kubectl apply -f /usr/local/src/argocd-server-parameters.yaml"],
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
    repoURL: "{argocd["repository_url"]}"
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
        "k3s kubectl diff "
        "-f /usr/local/src/argocd-root-application.yaml >/dev/null 2>&1; "
        "case $? in 0) printf current;; *) printf drifted;; esac"
    ),
)
if root_application_changed or root_application_state != "current":
    server.shell(
        name="Apply the Mashu root application",
        commands=["k3s kubectl apply -f /usr/local/src/argocd-root-application.yaml"],
    )

age_identity_source = Path(".age-key.txt")
age_identity_available = age_identity_source.is_file()

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
        "-n sops-secrets-operator -o jsonpath='{.data.keys\\.txt}' "
        "2>/dev/null | awk 'length { found=1 } END { "
        'if (found) printf "present"; else printf "absent" }\''
    ),
)
age_secret_sha256 = host.get_fact(
    Command,
    command=(
        "k3s kubectl get secret sops-age-identity "
        "-n sops-secrets-operator -o jsonpath='{.data.keys\\.txt}' "
        "2>/dev/null | base64 --decode | sha256sum | cut -d' ' -f1"
    ),
)
age_secret_ready = age_secret_state == "present" and bool(age_secret_sha256)

if not age_identity_available and not age_secret_ready:
    raise RuntimeError(
        "Argo CD requires .age-key.txt when the SOPS age identity Secret "
        "is missing or incomplete"
    )

if age_identity_available:
    age_identity_sha256 = hashlib.sha256(age_identity_source.read_bytes()).hexdigest()

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

    if (
        age_identity_changed
        or not age_secret_ready
        or age_secret_sha256 != age_identity_sha256
    ):
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
