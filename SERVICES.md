# Service Setup

This document contains the secret procedures and manual setup actions for the
host and its services. Complete only the sections that apply to a new install
or a credential change.

Set these variables before you use the commands:

```bash
export HOSTNAME="host"
export DOMAIN="example.com"
```

## Secret Rules

SOPS encrypts the Kubernetes secrets in this repository. The SOPS Secrets
Operator decrypts them in the cluster.

Keep these recovery items in a password manager and in a secure backup:

- The Age identity
- The administrator SSH private key
- Application administrator passwords
- Account recovery codes
- Storage and backup account credentials

Do not put a plain secret in the repository. Do not decrypt a secret to a
temporary file in the repository. Do not show a decrypted secret in terminal
output.

### Create the Age identity

Create one Age identity:

```bash
age-keygen -o .age-key.txt
age-keygen -y .age-key.txt
```

Set the public recipient in `.sops.yaml`. The recipient is not a secret.

Do not commit `.age-key.txt`. Store the file in a password manager and in a
secure offline backup. Pyinfra copies this identity to the host so that the
SOPS Secrets Operator can use it.

### Edit an encrypted secret

Use `sops` to edit an existing encrypted file:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/apps/<application>/credentials.sops.yaml
```

Save and close the editor. SOPS encrypts the protected values before it writes
the file.

For one scalar value, use `sops set --value-stdin`. The input must be a JSON
value. Use `yq` to encode the value before SOPS receives it:

```bash
read -rsp 'Secret value: ' SECRET_VALUE
printf '\n'
printf '%s' "$SECRET_VALUE" |
  yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt \
    sops set --value-stdin <secret-file>.sops.yaml '<SOPS-index>'
unset SECRET_VALUE
```

This command changes the encrypted file in place. Do not use a shell redirect
to create a plain-text secret file.

Confirm that SOPS can decrypt the file. Discard the plain output:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --decrypt <secret-file>.sops.yaml >/dev/null
```

### Add an encrypted secret

Create a `SopsSecret` resource with its required `data` or `stringData`
fields. Encrypt these fields in place:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --encrypt --in-place <secret-file>.sops.yaml
```

Add the file to the applicable `kustomization.yaml` file.

## External Infrastructure

### DNS records

Create DNS-only A and AAAA records for the public service names. Point the A
records to the public IPv4 address. Point the AAAA records to the public IPv6
address.

The current manifests use these name patterns:

- `*.${HOSTNAME}.${DOMAIN}`
- `git.${DOMAIN}`
- `id.${DOMAIN}`
- `netbird.${DOMAIN}`
- `rancher.${DOMAIN}`

Change the manifests if you use different names.

### Network ingress

Open the core ports in [README.md](README.md). Open an additional port only
when a service section below requires it.

## cert-manager and Cloudflare

cert-manager uses a Cloudflare API token to complete DNS-01 challenges. Use a
token that can read the required zone and edit its DNS records.

### Create the API token

Use the current
[Cloudflare token procedure](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
and the
[cert-manager permission requirements](https://cert-manager.io/docs/configuration/acme/dns01/cloudflare/):

1. Sign in to the Cloudflare dashboard.
2. Open **My Profile** and then **API Tokens**.
3. Select **Create Token**.
4. Use the **Edit zone DNS** template, or create a custom token.
5. Set one permission to **Zone**, **DNS**, and **Edit**.
6. Set a second permission to **Zone**, **Zone**, and **Read**.
7. Include only the DNS zone for `$DOMAIN`.
8. Review the summary and create the token.
9. Copy the token when Cloudflare shows it. Cloudflare does not show it again.

Do not save the token in `.cloudflare-api-token` or another plain-text file.

### Store the API token

Read the token without terminal echo. Store it directly in the existing
encrypted resource:

```bash
read -rsp 'Cloudflare API token: ' CLOUDFLARE_API_TOKEN
printf '\n'
printf '%s' "$CLOUDFLARE_API_TOKEN" |
  yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt \
    sops set --value-stdin \
    kubernetes/platform/certificate-issuers/cloudflare-api-token.sops.yaml \
    '["spec"]["secretTemplates"][0]["stringData"]["api-token"]'
unset CLOUDFLARE_API_TOKEN
```

Commit only the encrypted `.sops.yaml` file.

Confirm that the secret is valid and wait for Argo CD to apply it:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --decrypt \
  kubernetes/platform/certificate-issuers/cloudflare-api-token.sops.yaml \
  >/dev/null

ssh "$HOSTNAME" \
  'sudo k3s kubectl -n cert-manager get sopssecret,secret'

ssh "$HOSTNAME" \
  'sudo k3s kubectl get certificate,certificaterequest,challenge -A'
```

Revoke the old token in the Cloudflare dashboard after the certificates are
ready.

## Argo CD

Create a local tunnel if the public route is not ready:

```bash
ssh -L 8080:127.0.0.1:8080 "$HOSTNAME" \
  'sudo k3s kubectl -n argocd port-forward \
  service/argocd-server 8080:443 --address 127.0.0.1'
```

Get the initial administrator password:

```bash
ssh "$HOSTNAME" \
  "sudo k3s kubectl -n argocd get secret \
  argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo"
```

Open `https://localhost:8080` and sign in as `admin`. Change the password and
store it in a password manager. After the public route is ready, use
`https://argocd.${HOSTNAME}.${DOMAIN}`.

The public GitHub mirror does not require a repository credential. If the
repository becomes private, create a read-only repository credential and
store it as a SOPS-encrypted Kubernetes secret.

## Argus

Open `https://argus.${HOSTNAME}.${DOMAIN}` after the Argus and Pomerium
Applications are healthy. Pocket ID protects the route through Pomerium.

Argus compares upstream releases with the versions in the public GitHub
mirror. Its inventory is in `kubernetes/apps/argus/config.yml`. Add or remove
services there and let Argo CD reconcile the ConfigMap. The inventory
is read-only in the web interface, while approval and skipped-release state is
stored in the `argus-data` volume.

### Configure the GitHub token

Argus reads the GitHub token from the SOPS-managed `argus-credentials` Secret
through `ARGUS_SERVICE_LATEST_VERSION_ACCESS_TOKEN`. For this public inventory,
use a GitHub personal access token with read-only public access, an expiration
date, and no write scopes. Store it with `sops set`; never place it in
`config.yml` or another plain file. A token rotation requires recreating the
Argus pod after the Secret reconciles because environment variables are read
only when the container starts. See the repository's standard SOPS procedure
above.

```bash
read -rsp 'GitHub token for Argus: ' ARGUS_GITHUB_TOKEN; printf '\n'
printf '%s' "$ARGUS_GITHUB_TOKEN" | yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/apps/argus/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["GITHUB_TOKEN"]'
unset ARGUS_GITHUB_TOKEN
```

### Configure Discord notifications

Create a Discord webhook and copy its URL. Argus sends a notification when it
finds a new release for any tracked component. Store the webhook ID and token
from the URL in the SOPS-managed `argus-credentials` Secret:

```bash
read -rsp 'Argus Discord webhook URL: ' ARGUS_DISCORD_WEBHOOK_URL; printf '\n'
ARGUS_DISCORD_WEBHOOK_ID=${ARGUS_DISCORD_WEBHOOK_URL%/*}
ARGUS_DISCORD_WEBHOOK_ID=${ARGUS_DISCORD_WEBHOOK_ID##*/}
ARGUS_DISCORD_TOKEN=${ARGUS_DISCORD_WEBHOOK_URL##*/}
ARGUS_DISCORD_WEBHOOK_ID="$ARGUS_DISCORD_WEBHOOK_ID" \
  yq -n -o=json -I=0 'strenv(ARGUS_DISCORD_WEBHOOK_ID)' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/apps/argus/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["DISCORD_WEBHOOK_ID"]'
ARGUS_DISCORD_TOKEN="$ARGUS_DISCORD_TOKEN" \
  yq -n -o=json -I=0 'strenv(ARGUS_DISCORD_TOKEN)' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/apps/argus/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["DISCORD_TOKEN"]'
unset ARGUS_DISCORD_WEBHOOK_URL ARGUS_DISCORD_WEBHOOK_ID ARGUS_DISCORD_TOKEN
```

After Argo CD deploys the Secret, restart Argus and test the notifier:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argus rollout restart deployment/argus && \
  sudo k3s kubectl -n argus rollout status deployment/argus --timeout=120s'
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argus exec deployment/argus -- \
  /usr/bin/argus -config.file=/app/config.yml -test.notify discord'
```

No commands or update webhooks are configured. Approving a release records the
decision in Argus but does not change Git or the cluster. Use the matching
Makefile target, review its diff, then commit and push it. Argus clears the
version difference after the GitHub mirror receives the new revision.

### Update applications

Applications are the workloads under `kubernetes/apps` and application-like
platform workloads such as Backrest. Argo CD owns their live Kubernetes
resources. Update the pinned image with its Makefile target; do not run a
direct, non-dry-run `kubectl apply`.

For example:

```bash
make pomerium version=v0.33.1
```

Validate the YAML, render both the application and cluster, and ask the live
API server to validate the rendered resources without saving them:

```bash
yq '.' kubernetes/apps/<application>/deployment.yaml >/dev/null

kubectl kustomize kubernetes/apps/<application> >/dev/null
kubectl kustomize "kubernetes/clusters/${HOSTNAME}" >/dev/null

kubectl kustomize kubernetes/apps/<application> |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl apply --dry-run=server \
    -n <namespace> -f -'

kubectl kustomize kubernetes/apps/<application> |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl diff --server-side \
    -n <namespace> -f -'

git diff --check
pre-commit run --all-files
git diff
```

Commit and push after reviewing the diff. Argo CD deploys the commit. Monitor
the child Application and workload rather than applying the render manually:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argocd get application <application> --watch'

ssh "$HOSTNAME" \
  'sudo k3s kubectl -n <namespace> rollout status \
  deployment/<application> --timeout=300s'
```

### Update system applications

System applications include Gateway API, Traefik, cert-manager, Rancher, and
the other child Applications under `kubernetes/clusters/$HOSTNAME`. Argo CD
owns them, but changes to CRDs, controllers, and charts can affect every
application. Update and verify one system application per commit.

For a Helm-backed system application, change `targetRevision` and any
explicit image tag or values that must move with the chart:

```bash
make traefik-chart version=<new-chart-version>
make traefik-image version=<compatible-image-version>
```

```yaml
# kubernetes/clusters/<host>/<application>.yaml
spec:
  source:
    repoURL: <official-chart-repository>
    chart: <chart>
    targetRevision: <new-chart-version>
    helm:
      values: |
        image:
          tag: <compatible-image-version>
```

Forgejo and Netdata are multi-source Applications. For those, update the Helm
entry in `spec.sources[]`, not a nonexistent `spec.source`. Select the entry by
its chart name when extracting its values; do not rely on its array position:

```bash
yq -r '.spec.sources[] | select(.chart == "forgejo") | .helm.values' \
  "kubernetes/clusters/${HOSTNAME}/forgejo.yaml" |
  helm template forgejo forgejo \
    --repo https://code.forgejo.org/forgejo-helm \
    --version '<new-chart-version>' \
    --namespace forgejo \
    --kube-version '<current-kubernetes-version>' \
    --values - >/dev/null
```

First validate the child Application object itself:

```bash
yq '.' "kubernetes/clusters/${HOSTNAME}/<application>.yaml" >/dev/null

yq '.' "kubernetes/clusters/${HOSTNAME}/<application>.yaml" |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl apply --dry-run=server -n argocd -f -'
```

That check does not render the remote chart. Render the chart with the exact
repository, version, Kubernetes version, and values. This Traefik example
shows the pattern for an Application whose values are stored as a YAML block:

```bash
NEW_CHART_VERSION='<new-chart-version>'

helm show chart traefik \
  --repo https://traefik.github.io/charts \
  --version "$NEW_CHART_VERSION"

yq -r '.spec.source.helm.values' \
  "kubernetes/clusters/${HOSTNAME}/traefik.yaml" |
  helm template traefik traefik \
    --repo https://traefik.github.io/charts \
    --version "$NEW_CHART_VERSION" \
    --namespace traefik \
    --kube-version '<current-kubernetes-version>' \
    --values - >/dev/null
```

For a Kustomize-backed system application such as Gateway API, render its
actual resources. Use Argo CD's field manager when testing server-side CRD
updates so the dry run follows the live ownership model:

```bash
kubectl kustomize kubernetes/platform/gateway-api >/dev/null

kubectl kustomize kubernetes/platform/gateway-api |
  ssh "$HOSTNAME" \
    'sudo k3s kubectl apply --server-side --dry-run=server \
    --field-manager=argocd-controller -f -'
```

Finally render the root configuration, run the repository checks, and review
the change:

```bash
kubectl kustomize "kubernetes/clusters/${HOSTNAME}" >/dev/null
git diff --check
pre-commit run --all-files
git diff
```

After pushing, wait for the changed system Application to become `Synced` and
`Healthy`. Check dependent resources before starting the next system update:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n argocd get applications'

ssh "$HOSTNAME" \
  'sudo k3s kubectl get gateway,httproute -A'

ssh "$HOSTNAME" \
  'sudo k3s kubectl get certificate,certificaterequest -A'
```

### Update Argo CD

Pyinfra bootstraps and upgrades Argo CD. Update its version and manifest
checksum together, then run an Argo CD-only Pyinfra dry run. The Makefile
downloads the exact tagged manifest and calculates its checksum:

```bash
make argocd version=<new-version>
```

Commit the values before the maintenance window; the Git commit does not
upgrade Argo CD. Apply it explicitly and run the same dry run again to confirm
idempotency:

```bash
TASKS=argocd \
  uv run pyinfra inventory.py deploy.py \
  --diff --dry --sudo --limit "$HOSTNAME"
```

### Update K3s system components

Pyinfra owns K3s. The Makefile updates `k3s["version"]` and
`k3s["installer_sha256"]` together and derives the installer URL from the
version:

```bash
make k3s version=v<new-kubernetes-version>+k3s<revision>
```

Before changing the Kubernetes minor version, check the Rancher and K3s
support matrices and the release notes for Rancher, K3s, Traefik, cert-manager,
and Gateway API. If Rancher needs a newer version for the target Kubernetes
minor, update Rancher first and wait for it to become `Synced` and `Healthy`
before applying the K3s update.

Confirm that the tagged binary exists and run the static checks:

```bash
K3S_VERSION='v<new-kubernetes-version>+k3s<revision>'
curl -fsSIL \
  "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION}/k3s" \
  >/dev/null

ruff check inventory.py tasks/k3s.py
git diff --check
pre-commit run --all-files
git diff
```

Inspect cluster health, save an etcd snapshot, and run a K3s-only Pyinfra dry
run before applying the update:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl get nodes -o wide && \
  sudo k3s kubectl get pods -A'

ssh "$HOSTNAME" \
  'sudo k3s etcd-snapshot save --name pre-k3s-update && \
  sudo k3s etcd-snapshot list'

TASKS=k3s \
  uv run pyinfra inventory.py deploy.py \
  --diff --dry --sudo --limit "$HOSTNAME"
```

Review the Pyinfra operations and commit the pins. The Git commit does not
upgrade K3s; run the following only during the maintenance window:

```bash
TASKS=k3s \
  uv run pyinfra inventory.py deploy.py \
  --diff --sudo --limit "$HOSTNAME"
```

Afterward, verify the node, system pods, and Argo CD applications. Run the
same Pyinfra command again with `--dry`; it should report no K3s changes.

```bash
ssh "$HOSTNAME" \
  'sudo k3s --version && \
  sudo k3s kubectl get nodes -o wide && \
  sudo k3s kubectl get pods -A && \
  sudo k3s kubectl -n argocd get applications'

TASKS=k3s \
  uv run pyinfra inventory.py deploy.py \
  --diff --dry --sudo --limit "$HOSTNAME"
```

## Rancher

Open `https://rancher.${DOMAIN}` after Argo CD reports that Rancher is healthy.
Use the bootstrap password for the first sign-in:

```bash
ssh "$HOSTNAME" \
  "sudo k3s kubectl -n cattle-system get secret bootstrap-secret \
  -o jsonpath='{.data.bootstrapPassword}' | base64 -d; echo"
```

Set a permanent administrator password. Store the password in a password
manager. Keep one local administrator account for recovery.

### Rancher Compliance

Rancher Compliance adds a **Compliance** tab to the local cluster in Rancher.
The tab can run a manual scan or schedule recurring scans. Use
`k3s-cis-1.12-profile` for Mashu and schedule it at midnight each day with
`0 0 * * *`. Set a report retention count for the schedule.

Available profiles:

- `aks-profile-1.7`
- `cis-1.9-profile`
- `cis-1.10-profile`
- `cis-1.11-profile`
- `cis-1.12-profile`
- `eks-profile-1.5.0`
- `gke-profile-1.6.0`
- `k3s-cis-1.9-profile`
- `k3s-cis-1.10-profile`
- `k3s-cis-1.11-profile`
- `k3s-cis-1.12-profile`
- `rke2-cis-1.9-profile`
- `rke2-cis-1.10-profile`
- `rke2-cis-1.11-profile`
- `rke2-cis-1.12-profile`

## Backrest

The encrypted Backrest resource contains these values:

- The Storage Box SSH private and public keys
- The pinned SSH `known_hosts` data
- The Restic repository password
- The Discord webhook URL

They are in
`kubernetes/platform/backrest/credentials.sops.yaml`. The repository address,
path, plan, schedule, and retention policy are in
`kubernetes/platform/backrest/deployment.yaml`.

Edit the Backrest secrets with SOPS:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/platform/backrest/credentials.sops.yaml
```

Set the repository password directly when creating or rotating it:

```bash
read -rsp 'Backrest repository password: ' BACKREST_REPOSITORY_PASSWORD; printf '\n'
printf '%s' "$BACKREST_REPOSITORY_PASSWORD" | yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/platform/backrest/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["repository-password"]'
unset BACKREST_REPOSITORY_PASSWORD
```

Set or rotate the Discord webhook URL:

```bash
read -rsp 'Backrest Discord webhook URL: ' BACKREST_DISCORD_WEBHOOK_URL; printf '\n'
printf '%s' "$BACKREST_DISCORD_WEBHOOK_URL" | yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/platform/backrest/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["discord-webhook-url"]'
unset BACKREST_DISCORD_WEBHOOK_URL
```

Use the SOPS editor above for the multiline SSH keys and `known_hosts` value.

Add the Backrest public key to the Storage Box account. Confirm that the
repository path is unique to `$HOSTNAME`. Store the Storage Box credentials
and the Restic repository password in a password manager.

Open `https://backrest.${HOSTNAME}.${DOMAIN}`. Create the administrator account
and the host instance. Store the administrator password in a password manager.

Restart Backrest after it creates its initial configuration. The init
container then adds the repository and plan from Git:

```bash
ssh "$HOSTNAME" \
  'sudo k3s kubectl -n backrest rollout restart deployment/backrest'

ssh "$HOSTNAME" \
  'sudo k3s kubectl -n backrest rollout status deployment/backrest'
```

Open the repository and list its snapshots. Run one backup and restore test.

## Pocket ID

The Pocket ID encryption key is in
`kubernetes/apps/pocket-id/credentials.sops.yaml`. Keep the encryption key and
the Pocket ID data volume together during a restore.

Edit the Pocket ID secret with SOPS:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/apps/pocket-id/credentials.sops.yaml
```

Generate and store a new encryption key without printing it:

```bash
openssl rand -base64 32 | tr -d '\n' | yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
  kubernetes/apps/pocket-id/credentials.sops.yaml \
  '["spec"]["secretTemplates"][0]["stringData"]["ENCRYPTION_KEY"]'
```

For a new instance, complete the initial administrator setup at
`https://id.${DOMAIN}`. Register a passkey and store the recovery information
in a password manager.

Create an OIDC client for Pomerium. Use this callback URL:

```text
https://pomerium.$DOMAIN/oauth2/callback
```

Copy the client ID and client secret to the Pomerium encrypted resource. Test
the Pocket ID sign-in before you remove another recovery method.

## Pomerium

The Pomerium OIDC client ID, OIDC client secret, and cookie secret are in
`kubernetes/apps/pomerium/credentials.sops.yaml`.

Edit the OIDC values with SOPS:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/apps/pomerium/credentials.sops.yaml
```

Set the Pocket ID client values directly:

```bash
for KEY in IDP_CLIENT_ID IDP_CLIENT_SECRET; do
  read -rsp "Pomerium ${KEY}: " POMERIUM_VALUE; printf '\n'
  printf '%s' "$POMERIUM_VALUE" | yq -o=json -I=0 '.' |
    SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
    kubernetes/apps/pomerium/credentials.sops.yaml \
    "[\"spec\"][\"secretTemplates\"][0][\"stringData\"][\"${KEY}\"]"
done
unset KEY POMERIUM_VALUE
```

Generate and store a new 32-byte cookie secret without printing it:

```bash
openssl rand -base64 32 |
  tr -d '\n' |
  yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt \
    sops set --value-stdin \
    kubernetes/apps/pomerium/credentials.sops.yaml \
    '["spec"]["secretTemplates"][0]["stringData"]["COOKIE_SECRET"]'
```

Open the encrypted resource with SOPS. Set `IDP_CLIENT_ID` and
`IDP_CLIENT_SECRET` to the Pocket ID client values.

The routes and access policies are in
`kubernetes/apps/pomerium/config-map.yaml`. Add a route there when a service
must use Pocket ID authentication. Also add its Kubernetes `HTTPRoute` to
`kubernetes/apps/pomerium/routes.yaml`.

Test one protected service in a private browser window. Confirm that Pocket ID
sign-in returns the browser to the service.

## NetBird

### Required network access

| Protocol | Destination port | Purpose |
| --- | ---: | --- |
| UDP | 3478 | NetBird server STUN |

The encrypted NetBird resource contains the complete server configuration and
the dashboard OIDC settings. It is in
`kubernetes/apps/netbird/credentials.sops.yaml`. The NetBird data volume
contains the peers, users, policies, and server state. Back up and restore this
volume.

Edit the NetBird server and dashboard settings with SOPS:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/apps/netbird/credentials.sops.yaml
```

Set the dashboard's Pocket ID client values directly:

```bash
for KEY in AUTH_CLIENT_ID AUTH_CLIENT_SECRET; do
  read -rsp "NetBird ${KEY}: " NETBIRD_VALUE; printf '\n'
  printf '%s' "$NETBIRD_VALUE" | yq -o=json -I=0 '.' |
    SOPS_AGE_KEY_FILE=.age-key.txt sops set --value-stdin \
    kubernetes/apps/netbird/credentials.sops.yaml \
    "[\"spec\"][\"secretTemplates\"][1][\"stringData\"][\"${KEY}\"]"
done
unset KEY NETBIRD_VALUE
```

Use the SOPS editor above for the complete multiline server `config.yaml`.

For a new NetBird server, create its Pocket ID OIDC client and update the
encrypted server and dashboard configuration. Keep the public server name at
`https://netbird.${DOMAIN}`. Test dashboard sign-in, peer connections, relay,
and STUN before you use the server for recovery access.

## Forgejo and Forgejo Runner

### Required network access

| Protocol | Destination port | Purpose |
| --- | ---: | --- |
| TCP | 23 | Forgejo SSH |

Forgejo stores its application data, users, and administrator credentials in
its data volume. For a fresh install, create the administrator account and
store its password and recovery information in a password manager.

Create an instance runner token in the Forgejo administrator interface. Open
**Site Administration**, **Actions**, and **Runners**. Create a runner and copy
its registration token.

Store the token directly in the encrypted resource:

```bash
read -rsp 'Forgejo runner token: ' FORGEJO_RUNNER_TOKEN
printf '\n'
printf '%s' "$FORGEJO_RUNNER_TOKEN" |
  yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt \
    sops set --value-stdin \
    kubernetes/apps/forgejo/credentials.sops.yaml \
    '["spec"]["secretTemplates"][0]["stringData"]["FORGEJO_RUNNER_TOKEN"]'
unset FORGEJO_RUNNER_TOKEN
```

The runner uses this token only when its persistent runner identity does not
exist.

After a token rotation, remove the old runner identity or register a new
runner. Confirm that one test workflow completes.

## Netdata

Create a Discord webhook in the Discord server that receives alerts. Open
**Server Settings**, **Integrations**, and **Webhooks**. Create the webhook and
copy its URL.

Store the URL directly in the encrypted resource:

```bash
read -rsp 'Discord webhook URL: ' NETDATA_DISCORD_WEBHOOK_URL
printf '\n'
printf '%s' "$NETDATA_DISCORD_WEBHOOK_URL" |
  yq -o=json -I=0 '.' |
  SOPS_AGE_KEY_FILE=.age-key.txt \
    sops set --value-stdin \
    kubernetes/apps/netdata/notifications.sops.yaml \
    '["spec"]["secretTemplates"][0]["stringData"]["NETDATA_DISCORD_WEBHOOK_URL"]'
unset NETDATA_DISCORD_WEBHOOK_URL
```

Revoke the old webhook after Argo CD deploys the new value.

Open `https://netdata.${HOSTNAME}.${DOMAIN}`. Trigger and resolve one test
alarm. Confirm that Discord receives both messages.

## ArchiSteamFarm

ArchiSteamFarm stores its configuration and account credentials in the
`asf-config` volume. Use the protected interface at
`https://asf.${HOSTNAME}.${DOMAIN}` to configure it. Do not put Steam
credentials in Git. Back up the volume.

## Pingvin Share

Pingvin Share stores its users, configuration, uploads, and branding in its
data and image volumes. Open `https://share.${HOSTNAME}.${DOMAIN}` and create
the first administrator account. Store the administrator password in a
password manager. Back up both volumes.

## Syncthing

### Required network access

| Protocol | Destination port | Purpose |
| --- | ---: | --- |
| TCP | 22000 | Syncthing TCP transfers |
| UDP | 22000 | Syncthing QUIC transfers |

Syncthing stores its GUI credentials, device identity, peer configuration, and
data in the `syncthing-data` volume. Open
`https://syncthing.${HOSTNAME}.${DOMAIN}`. Set the GUI credentials and add the
required devices and folders. Store the GUI password and recovery information
in a password manager. Back up the volume when its identity or configuration
must survive a rebuild.

## Whoami

Whoami has no secret or manual application setup. Use it to test public
routing, TLS, IPv4, and IPv6.
