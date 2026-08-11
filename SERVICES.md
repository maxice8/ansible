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

Permit public TCP traffic on ports 22, 80, and 443 for IPv4 and IPv6. Permit
public UDP traffic on port 3478 for NetBird STUN. Keep K3s port 6443 private.

Syncthing also uses TCP and UDP port 22000 and UDP port 21027. Permit these
ports only when external Syncthing peers need direct access.

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

## Backrest

The encrypted Backrest resource contains these values:

- The Storage Box SSH private and public keys
- The pinned SSH `known_hosts` data
- The Restic repository password

They are in
`kubernetes/platform/backrest/credentials.sops.yaml`. The repository address,
path, plan, schedule, and retention policy are in
`kubernetes/platform/backrest/deployment.yaml`.

Edit the Backrest secrets with SOPS:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops kubernetes/platform/backrest/credentials.sops.yaml
```

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

For a new NetBird server, create its Pocket ID OIDC client and update the
encrypted server and dashboard configuration. Keep the public server name at
`https://netbird.${DOMAIN}`. Test dashboard sign-in, peer connections, relay,
and STUN before you use the server for recovery access.

### Enroll the host client

Pyinfra installs the NetBird client but does not enroll it. Start enrollment:

```bash
ssh "$HOSTNAME"
sudo netbird up --management-url "https://netbird.${DOMAIN}"
netbird status
ip -4 address show wt0
```

Approve or complete the enrollment in the NetBird interface. Set
`netbird_ipv4` in `inventory.py` to the address on `wt0`.

If the cluster hosts NetBird, rebuild K3s and Argo CD before you enroll the
host. Restore NetBird, start it, and then enroll the host client.

## Forgejo and Forgejo Runner

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

Syncthing stores its GUI credentials, device identity, peer configuration, and
data in the `syncthing-data` volume. Open
`https://syncthing.${HOSTNAME}.${DOMAIN}`. Set the GUI credentials and add the
required devices and folders. Store the GUI password and recovery information
in a password manager. Back up the volume when its identity or configuration
must survive a rebuild.

## Whoami

Whoami has no secret or manual application setup. Use it to test public
routing, TLS, IPv4, and IPv6.
