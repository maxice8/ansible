# Pyinfra Deployment Stack

This repository uses [Pyinfra](https://github.com/pyinfra-dev/pyinfra) to manage
the Mashu Ubuntu host. Legacy Fedora CoreOS files remain while Ryuu is retired.

## Requirements

### Python & Pyinfra

Use our `requirements.txt` to install the required python packages. I recommend [uv](https://github.com/astral-sh/uv).

```bash
uv pip sync requirements.txt
```

### Podman (if using Butane)

Podman is required to configure the Ignition file with Butane.

### Age + SOPS

[age](https://github.com/filosottile/age) and [sops](https://github.com/getsops/sops) are used to manage encrypted secrets files securely. To install using pacman in Arch Linux:

```bash
pacman -S age sops
```

### Configuration

Sops-encrypted `.env` files are used to store variables and secrets. Pyinfra automatically decrypts and processes these natively on execution.

- `group_vars/servers.sops.env` for cluster-wide or group configuration (see `group_vars/example.sops.env`)
- `host_vars/$HOSTNAME.sops.env` for node-specific configuration (see `host_vars/example.sops.env`)
- `$HOSTNAME.env` for initial Butane/Ignition provisioning configuration (see `example.env`)

To bootstrap a new machine target from templates:
```bash
cp group_vars/example.sops.env group_vars/servers.sops.env
cp host_vars/example.sops.env host_vars/ryuu.sops.env
cp example.env ryuu.env
```

### Encrypting Secrets

Both Pyinfra and Butane read from encrypted configuration files. Use `age` to encrypt/decrypt configuration keys via `sops`.

#### 1. Generate Key

Generate an age key file. **NEVER** commit this file to git. Store it securely in a password manager. If cloning this repository onto a new machine, copy the file over manually to restore decryption capabilities.

```bash
age-keygen -o .age-key.txt
```

#### 2. Configure .sops.yaml

Extract the public key by running `grep "public key:" .age-key.txt` and replace the `age` identity key string inside `.sops.yaml` so rules map flawlessly to your key.

#### 3. Encrypt the Configuration

With rules defined, encrypt your staging configuration files in place:

```bash
sops -e -i group_vars/servers.sops.env
sops -e -i host_vars/ryuu.sops.env
sops -e -i ryuu.env
```

*Note: To safely view or modify an encrypted file without leaking secrets to shell histories, always use the native SOPS wraparound instead of native editors like `nano` or `cat`:*
```bash
sops group_vars/servers.sops.env
sops host_vars/ryuu.sops.env
```

## Deploying

Use Pyinfra for Mashu. The Butane files apply only to the legacy Ryuu host.

### Butane

 A `Makefile` is provided to generate a Fedora CoreOS system ignition file. It dynamically decrypts your environment secrets, passes them into the Butane blueprint, and outputs a ready-to-flash `.ign` file compatible with `coreos-installer`.

```bash
make ryuu
```

### Pyinfra

Use Pyinfra to deploy the Mashu host state.

```bash
uv run pyinfra inventory.py deploy.py --sudo
```

## K3s

Use this procedure to rebuild the Mashu cluster. The current code is specific
to Mashu. Change the inventory, domain names, network interface, cluster path,
and backup repository before you use it for a different cluster.

### Store the recovery material

Store these secrets in Bitwarden:

- The `.age-key.txt` age identity
- The private SSH key for the Ubuntu administrator
- The Backrest administrator password
- The Restic repository password
- The Hetzner Storage Box password
- The OCI, Cloudflare, Forgejo, NetBird, and Pocket ID credentials
- The recovery codes for accounts that use multifactor authentication

Keep an offline copy of the repository. The repository contains these
SOPS-encrypted secrets:

- The Cloudflare DNS API token
- The Backrest SSH private key
- The Restic repository password
- The Hetzner Storage Box credentials

Do not store the K3s token, generated certificates, kubeconfig, Argo CD initial
password, Backrest JWT secret, or Backrest synchronization identity as recovery
requirements. Recreate these items with the cluster.

Confirm that the age identity can decrypt the files:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --decrypt kubernetes/platform/backrest/credentials.sops.yaml >/dev/null

SOPS_AGE_KEY_FILE=.age-key.txt \
  sops --decrypt kubernetes/platform/certificate-issuers/cloudflare-api-token.sops.yaml >/dev/null
```

### Prepare the host

Create an Ubuntu ARM64 host. Add OCI ingress rules for TCP ports 22, 80, and
443 for IPv4 and IPv6. Do not add a public rule for port 6443.

Point the Mashu DNS records to the new public IPv4 and IPv6 addresses. Confirm
that the public interface name is `enp0s6`.

Set the new SSH address and user in `inventory.py`. Configure the local SSH
client so this command works:

```bash
ssh mashu
```

Install the local Python requirements:

```bash
uv pip sync requirements.txt
```

Deploy the host baseline:

```bash
TASKS=user,ssh,netbird,kernel,services,firewall \
  uv run pyinfra inventory.py deploy.py --sudo
```

### Enroll NetBird

Start enrollment on Mashu:

```bash
ssh mashu
sudo netbird up --management-url https://netbird.maxice8.com
netbird status
ip -4 address show wt0
```

Complete the enrollment in the NetBird interface. Set `netbird_ipv4` in
`inventory.py` to the address on `wt0`.

### Install K3s and Argo CD

Run the complete deployment twice:

```bash
uv run pyinfra inventory.py deploy.py --sudo
uv run pyinfra inventory.py deploy.py --sudo
```

The second deployment must report no changes.

Create an Argo CD tunnel:

```bash
ssh -L 8080:127.0.0.1:8080 mashu \
  'sudo k3s kubectl -n argocd port-forward service/argocd-server 8080:443 --address 127.0.0.1'
```

Get the initial Argo CD password:

```bash
ssh mashu \
  "sudo k3s kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath='{.data.password}' | base64 -d; echo"
```

Open `https://localhost:8080`. Sign in as `admin`. Sync `mashu`, and then sync
these applications in order:

1. `gateway-api`
2. `traefik`
3. `public-gateway`
4. `cert-manager`
5. `sops-secrets-operator`
6. `certificate-issuers`
7. `staging-certificate`
8. `production-certificate`
9. `backrest`
10. `platform-routes`

Wait for each application to become healthy before you sync the next
application.

Restart the Argo CD server after the root application sets HTTP mode:

```bash
ssh mashu \
  'sudo k3s kubectl -n argocd rollout restart deployment/argocd-server'

ssh mashu \
  'sudo k3s kubectl -n argocd rollout status deployment/argocd-server'
```

Open `https://argocd.mashu.maxice8.com` and confirm that it works.

### Initialize Backrest

Open `https://backrest.mashu.maxice8.com`. Create the `mashu` instance and the
administrator account. Store the password in Bitwarden.

Restart Backrest so its init container adds the repository and backup plan:

```bash
ssh mashu \
  'sudo k3s kubectl -n backrest rollout restart deployment/backrest'

ssh mashu \
  'sudo k3s kubectl -n backrest rollout status deployment/backrest'
```

Confirm that Backrest can open `mashu-restic` and list its snapshots.

### Restore application data

Do not restore the K3s control plane. Pyinfra, Git, Argo CD, and SOPS recreate
it.

For each stateful application, declare zero replicas and sync it. Create its
PersistentVolumeClaim before you restore data. Keep the workload at zero
replicas during the restore.

```bash
ssh mashu
sudo k3s kubectl -n <namespace> scale deployment/<application> --replicas=0
sudo k3s kubectl get pvc -n <namespace>
sudo k3s kubectl get pv
```

Restore the application files from Backrest or Restic. Set the required owner
and mode. Start the application only after the restore is complete.

```bash
sudo chown -R <user>:<group> <volume-path>
sudo chmod -R <mode> <volume-path>
sudo k3s kubectl -n <namespace> scale deployment/<application> --replicas=1
sudo k3s kubectl -n <namespace> rollout status deployment/<application>
```

Restore and verify one application at a time.

### Verify the cluster

```bash
ssh mashu 'sudo k3s kubectl get pods -A'
ssh mashu 'sudo k3s kubectl -n argocd get applications'
ssh mashu 'sudo nft list table inet hostfilter'
curl -4 --fail https://whoami.mashu.maxice8.com/
curl -6 --fail https://whoami.mashu.maxice8.com/
curl -4 --fail https://backrest.mashu.maxice8.com/
curl -6 --fail https://backrest.mashu.maxice8.com/
```

Reboot the host. Run Pyinfra again and require an idempotent result.

### Public repository security

SOPS ciphertext can be public when the age identity stays private. SOPS
encrypts the secret values and authenticates the file contents. The age
recipient in `.sops.yaml` is public information.

The repository still exposes hostnames, public addresses, user names, service
versions, repository paths, firewall rules, and the names of secret fields.
This information can help an attacker identify targets.

Git history keeps old ciphertext and any plain secret that enters a commit. If
the age identity is compromised, an attacker can decrypt current and saved
ciphertext. Change the age identity, re-encrypt the files, and rotate every
affected service credential after such a compromise.

Use SOPS to edit secrets. Inspect staged changes before each push:

```bash
SOPS_AGE_KEY_FILE=.age-key.txt sops kubernetes/platform/backrest/credentials.sops.yaml
git diff --cached
git grep -n 'AGE-SECRET-KEY'
git grep -n 'BEGIN OPENSSH PRIVATE KEY'
```

The last two commands must not find a plain private key. Keep the Cloudflare
token limited to the required DNS zones. Keep Argo CD in manual-sync mode and
review changes before each sync.

## Code Quality & Static Analysis

We utilize **Ruff** for fast Python linting and code style formatting enforcement.

```bash
# Check for bugs, syntax errors, and unused components
uvx ruff check .

# Automatically apply standard format styling
uvx ruff format .
```
