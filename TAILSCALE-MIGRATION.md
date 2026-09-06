# Mashu: NetBird to Tailscale

Status: Tailscale and the transitional firewall are deployed. NetBird remains
running. Do not run removal steps until the cutover is authorized. No commit
or push has been made.

## Tailscale deployment result

- Enrolled and online as `mashu.neko-great.ts.net`, IPv4 `100.91.248.66`,
  IPv6 `fd7a:115c:a1e0::ed39:f844`, with `tag:server`.
- Tailscale SSH, accepted routes, and DNS preferences verified; no health
  warnings. K3s Ready; all 25 Argo CD Applications Synced/Healthy.
- Host DNS works; public whoami HTTPS returns 200 over IPv4 and IPv6.
- Tailscale SSH and passwordless sudo succeeded from the workstation. Peer
  ping used DERP(sao); a direct connection was not established in this test.
- A second apply reported all 17 operations unchanged.
- Firewall backup: `/root/tailscale-migration.Nh5mFU`.
- The NetBird deployment connection stalled before mutations; deployment
  succeeded using `--data ssh_hostname=2603:c025:4005:8f7e:0:b837:618:268c`.

The following baseline records describe the state before deployment.

## Verified on 2026-09-06

- Mashu runs Ubuntu 26.04.1 (resolute), with NetBird 0.78.1 installed.
- `netbird`, `netbird-gro`, and `k3s` are active. Tailscale is not installed.
- The `mashu` SSH alias connects to the NetBird IPv6 address on `wt0`.
- Direct public IPv6 SSH and passwordless sudo succeeded using the command
  below and the existing trusted host identity.
- All 25 Argo CD Applications are Synced/Healthy, including both NetBird apps.
- `netbird/netbird-server` has one ready replica; `netbird-data` is a bound
  1 GiB local-path PVC. Do not delete the namespace or PVC during cutover.
- Ruff lint/format and `git diff --check` passed. A live
  `TASKS=tailscale,firewall` Pyinfra dry run passed and proposed only the
  expected client installation/configuration and transitional firewall work.
  A second live dry run passed with automated enrollment included.
  Mocked checks passed for enrollment, missing keys, preference drift,
  already enrolled/stopped hosts, pending approval, and key-file cleanup.
  Actual package installation, enrollment, and post-install idempotence have
  not been tested yet.
- Enrollment now loads SOPS host settings. Its encryption/update round-trip
  and mocked enrollment-loading checks passed. The local Age identity and
  actual auth key must be supplied before repeating the live dry run.

## 1. Preserve recovery access and state

Keep a direct public SSH session open throughout the cutover:

```bash
ssh -o HostName=2603:c025:4005:8f7e:0:b837:618:268c \
  -o HostKeyAlias=mashu mashu
```

Before changes, verify that session's `SSH_CONNECTION` uses the public
address. Confirm OCI console access. Save root-only backups of
`/etc/netbird`, `/var/lib/netbird` if present, `/etc/nftables.conf`,
`/etc/systemd/system/homelab-firewall.service`,
`/etc/systemd/system/netbird-gro.service`, and the NetBird APT source and key.
Save `ip rule`, `ip route show table all`, `ip -6 route show table all`,
`nft list ruleset`, and the installed package version. Keep the NetBird
package available for rollback. Keep these backups off Git.

Check the NetBird dashboard for all enrolled peers, routes, DNS settings, and
policies. Migrate the needed peers and access rules to the intended tailnet
before retiring the server. NetBird and Tailscale use overlapping CGNAT
address space: compare actual routes and peer addresses during coexistence.

## 2. Install and enroll Tailscale

Add stateful OCI ingress for UDP 41641 on IPv4 and IPv6, source port All.
The host firewall retains `wt0`, UDP 51820, and server STUN UDP 3478 during
the transition. Create a non-ephemeral auth key authorized for `tag:server`
(and pre-approved when device approval is enabled). Ensure the tailnet policy
allows your user to SSH to `tag:server` as `ubuntu`. Review and then apply only
the selected tasks:

```bash
# Restore .age-key.txt from the password manager first.
make secret service=tailscale
TASKS=tailscale,firewall .venv/bin/pyinfra inventory.py deploy.py \
  --diff --dry --sudo --limit mashu
TASKS=tailscale,firewall .venv/bin/pyinfra inventory.py deploy.py \
  --diff --sudo --limit mashu
```

These commands still use the NetBird SSH alias, so run them before stopping
NetBird. The task installs and enrolls Tailscale, enables SSH, accepts tailnet
DNS and advertised routes, and requests `tag:server`. It does not remove
NetBird. The key is stored in `vars/settings.sops.yaml` through SOPS and
decrypted locally for initial enrollment. It is not saved in inventory or
persistent remote configuration. A running, enrolled host does not need the
local SOPS identity for preference reconciliation.

In the direct public SSH session:

```bash
sudo tailscale status
sudo tailscale netcheck
tailscale ip
```

Confirm Mashu appears in the intended tailnet with `tag:server`. Keep default
netfilter management enabled. From a second enrolled device, run
`tailscale ping` and `tailscale ssh ubuntu@<Mashu-Tailscale-address>`.
Check sudo in that session. Verify host DNS, accepted subnet routes, native
K3s node addresses, cluster health, and public HTTPS over IPv4 and IPv6.
Repeat the task dry run to check idempotence.

## 3. Stop the old client, verify, then uninstall

Run from the direct public session only after both access paths work:

```bash
sudo systemctl disable --now netbird-gro.service
sudo systemctl disable --now netbird.service
```

Open fresh public and Tailscale SSH sessions. Check DNS, routes, peer access,
K3s, and public HTTPS again. If checks fail, restart NetBird and investigate
before uninstalling anything. Once successful:

```bash
sudo apt-get remove netbird
sudo rm -f /etc/systemd/system/netbird-gro.service
sudo rm -f /etc/apt/sources.list.d/netbird.list
sudo rm -f /usr/share/keyrings/netbird-archive-keyring.asc
sudo systemctl daemon-reload
```

Do not purge client state, run autoremove, or flush the firewall. Update the
local `mashu` SSH alias to the verified replacement address before further
Pyinfra runs. Remove the `wt0` rule, UDP 51820, and `netbird.service` ordering
from `tasks/firewall.py`, then preview and apply `TASKS=firewall`. Leave UDP
3478 until server retirement. Check whether stopping the client left any
NetBird rules; remove only verified stale rules, preserving K3s/Tailscale.

## 4. Retire the Kubernetes server separately

Only proceed when every needed peer has migrated. Back up the server's
encrypted configuration and a consistent copy of its data volume. Confirm
snapshot recovery before cleanup. Record the PVC/PV and reclaim policy.

Prepare a focused GitOps change that removes `netbird.yaml` and
`netbird-dashboard.yaml` from `kubernetes/clusters/mashu/kustomization.yaml`
and removes those two Application manifests. Review the live Application
finalizers first: the local manifests omit resource-deletion finalizers, so
removing Applications can leave their workloads running. A live finalizer
can instead cause cascading deletion. Resolve this before publishing; keep
the PVC and namespace for rollback.

After the authorized Git push and root reconciliation, verify the child
Applications are gone. Explicitly stop/delete remaining server and dashboard
workloads and their routes/services without deleting the server PVC,
namespace, or secrets. Avoid a blanket namespace deletion or an unreviewed
`kubectl delete -k`. Once retired, remove the unused application definitions,
Argus entries, Makefile/update-script mappings, and NetBird setup docs.
Run `make check-updates` and render the root Kustomization before publishing
that cleanup. Retire the NetBird DNS records, Pocket ID OIDC client, host
UDP 3478 allowance, and OCI NetBird ingress rules after rollback is no longer
needed. Data destruction requires a separate retention decision.

## Rollback

Keep the direct public session. Before uninstalling, enable/start
`netbird.service` and `netbird-gro.service`. After uninstalling, restore the
APT source/key and package, saved client state, and GRO unit first, then run
`systemctl daemon-reload` and enable/start both services. Restore the prior
firewall file, validate with `nft --check -f /etc/nftables.conf`, and reload
`homelab-firewall.service`. If coexistence breaks routing, stop Tailscale
from the public session. Do not run `netbird down` or revoke its enrollment
before the rollback window closes. If the server was retired, restore its
GitOps Applications and workloads against the preserved data volume.

## References

- [Tailscale Ubuntu packages](https://pkgs.tailscale.com/stable/)
- [Tailscale CLI and enrollment options](https://tailscale.com/kb/1080/cli)
- [Tailscale netfilter ownership](https://tailscale.com/docs/reference/netfilter-modes)
