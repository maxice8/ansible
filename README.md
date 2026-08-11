# Homelab Deployment Stack

This repository manages one Ubuntu host and its K3s cluster.

Pyinfra manages the host, K3s, and the Argo CD bootstrap. Argo CD manages the
platform components and applications in Kubernetes.

## Requirements

### Python and Pyinfra

Use [uv](https://github.com/astral-sh/uv) to install the Python packages from
`requirements.txt`.

```bash
uv pip sync requirements.txt
```

### SSH

Install an SSH client. Add a local SSH configuration entry for the target
host. The entry must use the administrator and SSH key from `inventory.py`.
Pyinfra uses the local SSH configuration. Configure the host alias, user, key,
and host-key policy before you run Pyinfra. The connection must not require
interactive input.

This command must connect without a password prompt:

```bash
ssh "$HOSTNAME"
```

### Age and SOPS

Install [Age](https://github.com/FiloSottile/age) and
[SOPS](https://github.com/getsops/sops). For example, use this command on Arch
Linux:

```bash
sudo pacman -S age sops
```

### Kubernetes tools

Install `kubectl` and `yq` on the local system. The `kubectl kustomize` command
renders Kustomize resources. The `yq` command validates and selects YAML data.

## Configuration

Set these shell variables before you use the commands in this document:

```bash
export HOSTNAME="host"
export DOMAIN="example.com"
```

Set shared values in `plain_group_vars` in `inventory.py`. Set network and SSH
values in the host entry. Keep host-specific values in the host entry.

For a new host, update these items:

- The host name and SSH settings
- The private, public, and NetBird addresses
- The domain name
- The Argo CD repository URL
- The repository URLs in the child Application manifests
- The K3s version
- The cluster path in `tasks/argocd.py`
- Host names and addresses in the Kubernetes manifests

The current K3s configuration uses the private IPv4 address and the public
IPv6 address as node addresses. Do not use the NetBird address as a node
address.

## Secret Management

SOPS encrypts secret values in files that have the `.sops.yaml` suffix. The
file structure, resource names, and field names remain visible.

The SOPS Secrets Operator decrypts Kubernetes secrets in the cluster. Pyinfra
installs the Age identity that the operator uses.

See [SERVICES.md](SERVICES.md) for the Age identity procedure, each encrypted
secret, and each manual service setup action. Do not create plain-text secret
files in the repository.

## Host Deployment

### Prepare the host

Create an Ubuntu ARM64 host. In the OCI security list, keep each rule stateful
and set **Source Port Range** to **All**.

Create each required port rule twice:

| IP version | Source CIDR |
| --- | --- |
| IPv4 | `0.0.0.0/0` |
| IPv6 | `::/0` |

Create these core ingress rules:

| Protocol | Destination port | Purpose |
| --- | ---: | --- |
| TCP | 22 | Public SSH |
| TCP | 80 | HTTP and HTTPS redirects |
| TCP | 443 | Public HTTPS services |

See [SERVICES.md](SERVICES.md) for service-specific ports.

Point the required DNS records to the public IPv4 and IPv6 addresses. Update
the interface names in the firewall task if the host does not use the expected
public interface.

### Deploy the host baseline

Deploy the baseline before you install K3s:

```bash
TASKS=user,ssh,netbird,kernel,services,firewall \
  uv run pyinfra inventory.py deploy.py --sudo --limit "$HOSTNAME"
```

### Enroll the NetBird client

Pyinfra installs the NetBird client but does not enroll it. Start enrollment:

```bash
ssh "$HOSTNAME"
sudo netbird up --management-url "https://netbird.${DOMAIN}"
netbird status
ip -4 address show wt0
```

Approve or complete the enrollment in the NetBird interface. Set
`netbird_ipv4` in `inventory.py` to the address on `wt0`.

If this cluster also hosts the NetBird server, the server can be unavailable
during a full rebuild. In this case, install K3s and Argo CD first. Restore and
start the NetBird server. Then enroll the host, update `netbird_ipv4`, and run
the full Pyinfra deployment again.

### Install K3s and Argo CD

Run the full deployment:

```bash
uv run pyinfra inventory.py deploy.py --sudo --limit "$HOSTNAME"
```

Run it again. The second run must report no changes:

```bash
uv run pyinfra inventory.py deploy.py --sudo --limit "$HOSTNAME"
```

Pyinfra installs the selected K3s version. It installs the latest stable Argo
CD version during each deployment.

## Argo CD

### Open the user interface

Use the initial sign-in procedure in [SERVICES.md](SERVICES.md). After the
public route is healthy, use this address:

```text
https://argocd.$HOSTNAME.$DOMAIN
```

### Automatic synchronization

The root Application and all child Applications use automatic sync. Argo CD
also uses pruning and self-healing. Do not sync the applications in a manual
order.

Monitor the applications during the first deployment:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argocd get applications --watch'
```

Some applications can show `Progressing` while a required controller or CRD
starts. Wait for Argo CD to retry. Use a hard refresh if an Application does
not detect the current Git revision.

Automatic pruning deletes live resources that Git no longer defines.
Self-healing restores live changes to the values in Git. Review each change
before you push it.

Argo CD does not restore manual replica changes for these applications:

- ASF
- Forgejo
- NetBird
- Pingvin Share
- Pocket ID
- Syncthing

Argo CD restores manual replica changes for system services and stateless
applications.

## Backrest

Use the credential and initial setup procedures in
[SERVICES.md](SERVICES.md). Confirm that Backrest can open the repository and
list its snapshots.

## Restore Application Data

Treat the K3s control plane as disposable. Pyinfra, Git, Argo CD, and SOPS
recreate it. Restore only the application volumes that contain required data.

Scale one stateful application to zero replicas. Confirm that its PVC and PV
exist:

```bash
ssh "$HOSTNAME"
sudo k3s kubectl -n <namespace> scale deployment/<application> --replicas=0
sudo k3s kubectl -n <namespace> get pvc
sudo k3s kubectl get pv
```

Restore the volume from Backrest or Restic. Set the required owner and mode.
Keep the workload at zero replicas during the restore.

```bash
sudo chown -R <user>:<group> <volume-path>
sudo chmod -R <mode> <volume-path>
sudo k3s kubectl -n <namespace> scale deployment/<application> --replicas=1
sudo k3s kubectl -n <namespace> rollout status deployment/<application>
```

Restore and verify one application before you restore the next application.

## Verification

Check the cluster and the host firewall:

```bash
ssh "$HOSTNAME" 'sudo k3s kubectl get pods -A'
ssh "$HOSTNAME" 'sudo k3s kubectl -n argocd get applications'
ssh "$HOSTNAME" 'sudo nft list table inet hostfilter'
```

Test one public service with IPv4 and IPv6:

```bash
curl -4 --fail "https://whoami.${HOSTNAME}.${DOMAIN}/"
curl -6 --fail "https://whoami.${HOSTNAME}.${DOMAIN}/"
```

Reboot the host. Run the full Pyinfra deployment again. It must report no
changes.

## Routine Changes

Use Pyinfra for host changes. Use Kubernetes manifests and Argo CD for cluster
changes.

### Check a host change

Run a Pyinfra dry run before you deploy a host change:

```bash
uv run pyinfra inventory.py deploy.py --dry --sudo --limit "$HOSTNAME"
```

Use `TASKS` when you must limit the dry run to one or more tasks:

```bash
TASKS=firewall \
  uv run pyinfra inventory.py deploy.py --dry --sudo --limit "$HOSTNAME"
```

A dry run does not prove that every remote command is safe. Review the
generated operations before you run the deployment without `--dry`.

### Render Kubernetes resources

Render one application with Kustomize:

```bash
kubectl kustomize kubernetes/apps/<application>
```

Render the complete cluster configuration:

```bash
kubectl kustomize "kubernetes/clusters/${HOSTNAME}" >/dev/null
```

The cluster render validates the root Kustomization. It does not render the
source of each child Argo CD Application. Render a changed application path
separately.

### Run a server-side dry run

Send the rendered resources to the Kubernetes API without changing the
cluster:

```bash
kubectl kustomize kubernetes/apps/<application> |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl apply --dry-run=server -f -'
```

This command checks the live API schema, installed CRDs, and admission rules.
It does not save the resources.

Validate a child Argo CD Application definition in the same way:

```bash
yq '.' "kubernetes/clusters/${HOSTNAME}/<application>.yaml" |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl apply --dry-run=server -f -'
```

Use `kubectl diff` to compare rendered resources with live resources:

```bash
kubectl kustomize kubernetes/apps/<application> |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl diff --server-side -f -'
```

`kubectl diff` returns status 1 when it finds a difference. This status does
not mean that the command failed.

### Check a secret

Confirm that SOPS can decrypt each changed secret. Do not show the plain value:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --decrypt <secret-file>.sops.yaml >/dev/null
```

### Review and deploy

Use this sequence for a cluster change:

1. Edit the manifest or the encrypted secret.
2. Run `git diff --check`.
3. Render each changed Kustomization.
4. Run a server-side dry run.
5. Review `git diff`.
6. Stage the required files.
7. Review `git diff --cached`.
8. Commit and push the change.
9. Wait for the repository mirror.
10. Confirm that Argo CD reports `Synced` and `Healthy`.

Check Argo CD and the changed workload after the push:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argocd get applications'

ssh "$HOSTNAME" \
  'sudo k3s kubectl get pods -A'
```

Check recent warning events if a workload is not healthy:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl get events -A \
  --field-selector type=Warning --sort-by=.lastTimestamp'
```

Do not push a change that must not reach the live cluster. Automatic sync can
apply it after the mirror updates.

## Public Repository Security

SOPS ciphertext can be public if the Age identity stays private. The Age
recipient in `.sops.yaml` is public information.

The repository exposes host names, public addresses, user names, service
versions, paths, firewall rules, and secret field names. This information can
help an attacker.

Git keeps old ciphertext and any plain secret that enters its history. If an
attacker gets the Age identity, the attacker can decrypt current and saved
ciphertext. Create a new Age identity, encrypt the files again, and rotate all
affected credentials.

### Enable pre-commit

This repository uses [pre-commit](https://pre-commit.com/) to manage its Git
hooks. `requirements.txt` installs the framework. Enable it after each clone:

```bash
uv run pre-commit install --install-hooks
```

Run the hooks for all tracked files:

```bash
uv run pre-commit run --all-files
```

The configured hooks block these items:

- The Age identity file
- Private keys
- Secrets that Gitleaks detects in staged changes

The Gitleaks pre-commit hook scans staged changes. It does not audit all Git
history. Use a separate full-history scan in CI when you need that control.

Run the checks against staged changes without a commit:

```bash
uv run pre-commit run
```

Do not use `git commit --no-verify`. Git hooks are local controls. A user can
disable or bypass them. Add the same Gitleaks scan to CI if multiple users can
push to the repository.

Inspect staged changes before each commit:

```bash
git diff --cached
uv run pre-commit run
```

Give each token only the permissions that it needs.

## Code Quality and Static Analysis

Use Ruff to check and format the Python code:

```bash
uvx ruff check .
uvx ruff format .
```
