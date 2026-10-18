# Service setup and credentials

Run local commands inside the [devenv environment](README.md#development-environment).
Nix owns final service configuration; applications own their mutable state under
`/var/lib/data`. The repository contains no cutover scripts.

## SOPS identity

All active service credentials live in `secrets/mashu.sops.yaml`. SOPS encrypts
values; field names remain visible. On Mashu, sops-nix decrypts them using
`/var/lib/sops-nix/key.txt`, then systemd supplies private service credentials.
Plaintext credentials and identities must never enter Git, the Nix store or logs.

Restore the existing `.age-key.txt` from the password manager. Generate a new
identity only for an intentionally new installation, and update the public
recipient in `.sops.yaml` before encrypting its credentials. Keep the identity,
administrator SSH key, backup passwords and recovery codes separately recoverable.

For a **fresh host only**, provision the identity over the independent SSH path:

```sh
ssh mashu-admin 'sudo install -d -m 0700 /var/lib/sops-nix &&
  sudo sh -c "set -C; umask 077; cat > /var/lib/sops-nix/key.txt"' < .age-key.txt
```

The command refuses to overwrite an existing identity. Preserve Mashu's current
identity on redeployment. The local file is ignored; deployments do not copy it
into their source snapshot. Keep it locally only when needed for secret editing.

List/edit secrets and validate decryption without printing values:

```sh
python scripts/update_secret.py --list
make secret service=traefik
SOPS_AGE_KEY_FILE=.age-key.txt sops --decrypt secrets/mashu.sops.yaml >/dev/null
```

Empty prompt responses keep existing values. Backrest's editor opens the shared
encrypted document: edit only its intended fields. Use `make secret service=forgejo` for its structured INI credential as well. Deploy changes with the normal
Nix command; rotation is not complete until the consumer is checked.

## Required secrets and state

| Service | Secret fields in the shared encrypted document | Durable directory |
| --- | --- | --- |
| Traefik | `cloudflare_dns_api_token` | `traefik` (including ACME account/certificates) |
| Pomerium | `pomerium_cookie_secret`, `pomerium_shared_secret`, `pomerium_idp_client_id`, `pomerium_idp_client_secret` | `pomerium` (databroker/session state) |
| Pocket ID | `pocket_id_encryption_key` | `pocket-id` (SQLite, uploads and passkeys) |
| Syncthing heartbeat | `syncthing_heartbeat_url` | `syncthing` (device/configuration/database and synchronized data) |
| Forgejo | `forgejo_app_ini` | `forgejo` (database, repositories, attachments, SSH identity) |
| Release Argus | `argus_github_token`, `argus_discord_token`, `argus_discord_webhook_id` | `argus` (approval/release state) |
| Forgejo Runner | `forgejo_runner_registration_token` | `forgejo-runner` (persistent runner identity) |
| Netdata | `netdata_discord_url`, `netdata_heartbeat_url` | `netdata` (collector state and retained historical data) |
| Backrest | `backrest_config_json`, `backrest_ssh_key`, `backrest_known_hosts`, `backrest_repository_password` | `backrest` (configuration/history) and `backup-capture` (consistent exports) |
| Tailscale | `tailscale_auth_key` | `tailscale` (node/SSH identity) |
| ArchiSteamFarm | Configure Steam credentials through its private state/UI | `archisteamfarm` |
| Pingvin Share X | Configure users/OIDC through its state/UI | `pingvin-share` |

All directory names in the last column are beneath `/var/lib/data`. Existing
service ownership/modes are part of the deployment; do not change them globally.
Backrest backs up this one root. Existing historical Netdata files are retained,
but are not automatically displayed by the active host collector.

## Host DNS service

`services/unbound/default.nix` declares a hardened resolver on `127.0.0.1:53`
for UDP and TCP clients. Public queries are forwarded over TCP 53 to `9.9.9.9`,
`8.8.8.8` or `208.67.222.222`. UID 5010 can contact only those forwarders and
Tailscale's local `100.100.100.100:53`, and reply to clients. DNSSEC trust anchors
persist under `/var/lib/unbound`; the response cache is disposable. Upstream DNS
uses TCP, not TLS. No public DNS listener or ingress allowance is added.

`ts.net` and the IPv4/IPv6 tailnet reverse zones go only to MagicDNS over TCP.
Those private answers are unsigned, so validation is disabled only for those
zones and Unbound's default empty reverse zones are overridden. Public DNS keeps
its existing DNSSEC validation. TCP forwarding also avoids randomized UDP source
binds that Unbound's existing socket restrictions intentionally prohibit.

`services/application-dns.nix` creates an application-only resolver file with
`nameserver 127.0.0.1` and search suffix `neko-great.ts.net`. Native application
units bind a private directory containing that resolver over `/run/systemd/resolve`
**inside their mount namespaces**; portable units receive the file through the
shared `mashu` profile. Binding the whole directory prevents resolved's atomic
runtime-file replacements during boot from displacing a file-only bind mount.
Both wait for Unbound at startup. The host `/etc/resolv.conf`, systemd-resolved,
Tailscale's DNS ownership, node identity and administrator SSH retain their
existing configuration. Short tailnet names and full MagicDNS names therefore
remain available without routing host DNS back through Unbound.

Pingvin and CI containers use slirp's virtual DNS endpoint `10.0.2.3`, which
forwards through their native service's Unbound resolver. Host-loopback access
stays disabled; the UID firewalls allow only the resolver's localhost port 53.
Container `/etc/resolv.conf` must not use `127.0.0.1`, which denotes the container
itself. Traefik's ACME recursive resolver also points to Unbound; its existing
upstream authoritative propagation checks remain enabled.

Application firewall DNS allowances now target `127.0.0.1:53` instead of the
host's `127.0.0.53` stub. Existing application-specific connection permissions
are unchanged: resolving a tailnet name does not grant additional tailnet access.
A tailnet suffix change must also update the application search suffix.

The pre-cutover profile and resolver/container/portable configuration snapshots
are in `/var/backups/application-dns-before-20261018T195132Z`. Restore that profile
through `deploy.py` for rollback; it retains the prior application DNS paths.

Deployed on 2026-10-18 with System Manager profile
`/nix/store/09i7vf5d2xa617g2bvkdxp7fd1z1v2nf-system-manager`. Live checks verified
resolver mounts and public/MagicDNS queries in all twelve application contexts,
short names in native namespaces, and public/MagicDNS/short/reverse lookups in
Pingvin and an automatically removed CI container using a cached image. Fresh
Tailscale and public SSH, application health, HTTPS routes and existing
certificates passed; the host resolver and Tailscale process were unchanged.

Initial new TCP connections from Mashu to Hiyori's tailnet addresses on port 22000 timed out:
Hiyori's Tailscale daemon logged `no rules matched` because its policy excluded
Mashu (`tag:server`) as a source. After the user added the grant below, fresh TCP
connections from Syncthing UID 5001 succeeded over both IPv4 and IPv6. At the
user's request, Syncthing was restarted on 2026-10-18 at 21:02 UTC. Both Hiyori
and Hiiro reconnected with primary TCP sessions over Tailscale IPv6; additional
public connections remain available. All five folders returned to idle with zero
pending items or errors, and no systemd units were failed.

The user subsequently replaced the address-specific rule with this entry in the
[Tailscale access controls](https://login.tailscale.com/admin/acls). Fresh TCP
connections as UID 5001 to Hiyori succeeded again over both address families.

```json
{
  "src": ["tag:server"],
  "dst": ["maxice8@github"],
  "ip": ["tcp:22000", "udp:22000"]
}
```

This permits all servers to reach all personal devices owned by that user,
including future devices, on Syncthing's TCP/UDP port over both address families.
Existing peer configuration and local firewall allowances were left intact.
Post-reboot acceptance is recorded below; full CI workflow and forced ACME
renewal remain separate checks.


## Public services

| Address | Authentication / setup |
| --- | --- |
| `https://git.maxice8.com` | Forgejo's own accounts/OIDC; Git SSH uses `git.maxice8.com:23` |
| `https://id.maxice8.com` | Pocket ID passkeys and OIDC administration |
| `https://share.mashu.maxice8.com` | Pingvin's own accounts/OIDC |
| `https://pomerium.maxice8.com` | Authentication gateway for protected applications |
| `https://argus.mashu.maxice8.com` | Pomerium-protected release dashboard |
| `https://asf.mashu.maxice8.com` | Pomerium-protected Steam account management |
| `https://syncthing.mashu.maxice8.com` | Pomerium plus Syncthing GUI credentials |
| `https://netdata.mashu.maxice8.com` | Pomerium-protected monitoring |
| `https://backrest.mashu.maxice8.com` | Pomerium-protected backup administration |

Create initial application administrators only on fresh datasets. Preserve
existing accounts, passkeys, issuer URLs, OIDC clients and callbacks on upgrades.
Do not replace Pocket ID's encryption key as a routine password rotation.

## Traefik / Cloudflare

Use a Cloudflare token limited to Zone DNS Edit and Zone Read for the required
zone. Store it with `make secret service=traefik`. Traefik owns DNS-01 issuance;
certificates and account state persist in its own data directory. Check issuance
and HTTPS before revoking an old token. Required DNS names and ingress ports are
listed in README.md. The retired cluster's Argo/Rancher/whoami routes are absent.

### Traefik portable service

`services/traefik/default.nix` packages the pinned binary, static configuration
and file-provider routes into `traefik.raw`. Configuration changes replace the
image through the shared deployment hook. UID/GID 5002 and the existing
`/var/lib/data/traefik/acme.json` persist; the Cloudflare token is injected with
`LoadCredential`, never included in the image. The host still owns the firewall.
Systemd grants only `CAP_NET_BIND_SERVICE` for TCP 80/443, with health on loopback
9080. Attachment and boot enablement follow the same pattern as Argus/Pocket ID.

```sh
ssh mashu 'sudo -n portablectl inspect traefik; systemctl is-enabled traefik'
ssh mashu 'systemctl show traefik -p RootImage -p User -p CapabilityBoundingSet'
ssh mashu 'curl --fail http://127.0.0.1:9080/ping'
```

For a native-generation rollback, first run `sudo systemctl disable --now traefik`
and `sudo portablectl detach traefik`, then deploy the retained native profile.
Never use `--clean`: the certificate account and private keys must survive.
The pre-migration backup and native profile are recorded in
`/var/backups/traefik-before-portable-20261018T191254Z`.

Validated on Mashu on 2026-10-18 with the same 3.7.15 binary: all nine origin
HTTPS routes retain the original trusted certificate, HTTP redirects work, ACME
state and the runtime DNS token are unchanged, and the original state mount,
numeric identity, capability bounds and boot enablement are intact. Deployment
also checks both SSH paths, DNS, application health and public HTTPS. The shared
health retry tolerates Traefik's brief startup 404 before `/ping` is registered.
Certificate issuance/renewal and a full host reboot were not exercised.

## Pocket ID and Pomerium

Keep Pocket ID's canonical issuer `https://id.maxice8.com` stable. Create or retain
the Pomerium OIDC client with its exact callback URL shown by the provider. Store
client/cookie/shared credentials through `make secret service=pomerium`. Preserve
its databroker directory when maintaining existing sessions.

Test a real passkey login and protected-application redirect after identity or
OIDC changes. Loopback readiness checks alone do not exercise a browser login.

### Pocket ID portable service

`services/pocket-id/default.nix` packages the pinned application and embedded UI
into `pocket-id.raw`. The existing UID/GID 5004, issuer URL, encryption key,
database/uploads under `/var/lib/data/pocket-id`, firewall and loopback listeners
remain unchanged. The Francis task runtime still uses UDP 1414 on loopback;
public web traffic reaches TCP 1411 through Traefik/Pomerium.

Deployment attaches/replaces the image and enables `pocket-id.service` under
`system-manager.target`. The shared profile in `services/portable-profile.nix`
exposes application DNS, machine identity and logging; runtime systemd credentials
supply the encryption key. The image contains no key or user database.

```sh
ssh mashu 'sudo -n portablectl inspect pocket-id; systemctl is-enabled pocket-id'
ssh mashu 'systemctl show pocket-id -p RootImage -p User -p CapabilityBoundingSet'
ssh mashu 'curl --fail http://127.0.0.1:1411/.well-known/openid-configuration'
```

Before rollback to a native Pocket ID generation, run
`sudo systemctl disable --now pocket-id` and `sudo portablectl detach pocket-id`,
then deploy the retained native profile. Detachment retains identity data;
never use `--clean` for this rollback.

Validated on Mashu on 2026-10-18 using the same 2.18.0 binary: the existing user,
two passkeys, five OIDC clients, uploads, issuer metadata, signing keys and runtime
encryption key are unchanged. Database integrity, original state mount/ownership,
capability restrictions, login-page delivery, persistent boot enablement and repeat
deployment passed. SSH, DNS, application health and public HTTPS checks also passed.
The backup and native rollback profile are in
`/var/backups/pocket-id-before-portable-20261018T185106Z`. A full reboot was not
exercised; browser passkey authentication requires a user check.

## Argus and version updates

### Portable execution

Production Argus is built with `pkgs.portableService` in
`services/argus/default.nix`. Its image contains the executable, dependencies,
CA bundle and non-secret YAML configuration. Argus requires YAML for service
ordering; JSON previously decoded but left the monitoring order empty.

The image is always named `argus.raw`; only its immutable Nix store directory
changes with a new build. `portablectl` owns `argus.service` and its persistent
attachment under `/etc/systemd/system.attached`. The service is enabled under
`system-manager.target`, so host systemd starts it at boot without an attachment
wrapper or a continuously running `systemd-portabled` daemon.

Each portable application supplies `bin/activate-portable-<name>` in the built
host profile, using `services/activate-portable.nix`. After activating the host
configuration, `deploy.py` runs these scripts over SSH: each attaches a fresh
installation or uses `portablectl reattach --now` when the image path, persistent
unit attachment or shared profile differs. Unchanged attachments retain their
running processes. Host `systemctl enable --now` creates the normal boot
dependency and waits for the queued restart before HTTP readiness is checked.
Stopped services are started even when their attachments are unchanged. Host
configuration or credential changes can still restart affected services.
`make deploy` remains the complete deployment command.
The scripts and images are retained by the Nix profile for reproducibility and
rollback. Calling System Manager directly does not run this extra deployment step.

The Nix-declared `mashu` portable profile exposes machine identity, application DNS and
logging. Hardening stays in the image unit. UID/GID 5007, the egress firewall,
`127.0.0.1:8081`, runtime SOPS credentials and `/var/lib/data/argus` are preserved.
The image has a pre-created state mountpoint because SquashFS is read-only.

```sh
ssh mashu 'sudo -n portablectl list; sudo -n portablectl is-attached argus'
ssh mashu 'systemctl status argus; systemctl is-enabled argus'
ssh mashu 'systemctl show argus -p RootImage -p User -p CapabilityBoundingSet'
ssh mashu 'sudo -n systemctl restart argus'
ssh mashu 'curl --fail http://127.0.0.1:8081/api/v1/healthcheck'
```

Deploy a retained portable generation with
`python deploy.py deploy --store-path /nix/store/…`; its deployment script selects
that generation's image. Before reverting to an old native/runtime-wrapper
generation or removing Argus from the host configuration, detach it explicitly:

```sh
ssh mashu 'sudo -n systemctl disable --now argus; sudo -n portablectl detach argus'
```

Detachment retains application data. Never use `--clean` for an ordinary upgrade
or rollback. Database backups are separate from profile rollback; restoring an
old database also discards release decisions made since that backup.

The pre-portable database backup and native unit remain in
`/var/backups/argus-before-portable-20261018T093944Z`; its `profile` file records
the native rollback generation. The separate canary definition and build output
have been retired in favor of this production application.

Validated on Mashu on 2026-10-18: first attachment, replacement between distinct
immutable image paths, and repeat deployment all passed. `argus` has a single entry
in the portable inventory, its normal systemd boot link is enabled, and all 11
approval records, credential mounts and state ownership are preserved. SSH,
DNS, application and public HTTPS continuity checks passed. A full reboot was
not exercised. The migration backup, including retired canary state, is at
`/var/backups/argus-persistent-20261018T095654Z`.

### Production release tracking

Argus configuration is generated by `services/argus/default.nix`. It compares upstream
releases with package versions selected by Nix; Forgejo and Netdata additionally
have runtime HTTP version probes. Its dashboard is read-only except for release
approval/skipping state. Approval does not update Git or deploy a package.

`make secret service=argus` accepts a read-only public GitHub token and a complete
Discord webhook URL, storing the webhook ID/token separately. Deploy the change,
then verify delivery before revoking old credentials. Update packages through
`make update`, review/build them and explicitly deploy; no GitOps controller runs.

### Application portable services

The remaining application modules follow the same stable-image, persistent
attachment and shared health-check pattern:

| Service | Image | State and special runtime requirements |
| --- | --- | --- |
| Syncthing 2.1.6 | `syncthing.raw` | UID/GID 5001; device keys, index and all five synchronized folders stay under `/var/lib/data/syncthing`. The host heartbeat remains native. New synchronized folders must be inside that state root to be visible in the image. |
| ArchiSteamFarm 6.3.10.6 | `archisteamfarm.raw` | UID/GID 5013; bot configuration/session state remains under `/var/lib/data/archisteamfarm`. The image includes .NET, plugins and the UI, preserving its state-directory symlink. JIT and executable private temporary files remain allowed. |
| Pomerium 0.33.4 | `pomerium.raw` | UID/GID 5003; the original databroker persists, and four credentials enter through `LoadCredential`. Embedded Envoy uses Nix glibc via conventional loader paths, executable private temporary files and the existing loopback RPC range. |
| Forgejo 17.0.0 | `forgejo.raw` | UID/GID 5005; database, repositories, LFS and SSH host keys remain under `/var/lib/data/forgejo`. The image includes Git/LFS/SSH, signing/compression helpers, `/bin/sh`, `/usr/bin/env` and a minimal Forgejo account database for subprocesses. |

Host accounts, firewalls, credentials and backup/heartbeat units retain their
existing ownership. Each image binds only its own state directory; it does not
expose another application's data. Configuration changes rebuild the image and
reattach it during deployment.

The consistent pre-migration state backups, key/identity baseline, native units
and retained native profile are in
`/var/backups/remaining-before-portable-20261018T192401Z`. Syncthing's backup
contains its configuration/index/identity, not a second copy of synchronized
payloads. Those payloads stay in place and remain covered by normal backups.
For rollback to the recorded native profile, disable/stop and detach the four
portable services first, without `--clean`, then deploy that retained profile.

The Syncthing heartbeat checks local readiness through `ExecCondition`: an
intentional pause skips the external ping without marking the unit failed, and
the external monitor still detects a prolonged absence of heartbeats.

Validated on Mashu on 2026-10-18: the original identities, credentials and state
mounts are preserved; all four images have no Linux capabilities and are enabled
under `system-manager.target`. All five Syncthing folders returned to idle with
the same file/byte counts and both peers connected. ASF logged back into Steam.
Pomerium's components are ready, all five protected apps reach Pocket ID's login
page, and embedded Envoy loads Nix libraries. Forgejo's database integrity,
original record counts, repository refs, SSH host keys and Git access over SSH
and HTTPS are intact. All nine origin HTTPS routes retain their trusted
certificate. Repeat deployment passed the SSH, DNS and application continuity
gates, all seven portable units are in the live boot dependency graph, and no
units are failed. The validated host profile is
`/nix/store/4ldk68y37a7p1465gav5lvi2qgrj3rbr-system-manager`.
The user confirmed successful passkey logins after this migration. Git push and
CI acceptance are recorded below; LFS remains unchecked, while the user will
verify Pingvin upload/download and a fresh synchronized-file transfer. Backup
restoration and rollback exercises are deferred
at the user's request. The minimal NixOS ARM builder is retained; cross-compilation
work is not required for this migration.

Keep Unbound, Tailscale, Netdata, Backrest, the Forgejo runner and its Podman
engine native for their host/network/data/socket integration. Keep Pingvin Share X
on its pinned upstream OCI image. Firewalls, accounts, SOPS and maintenance units
also remain host services.

### Deployment and reboot acceptance (2026-10-18)

Profile used for reboot acceptance:
`/nix/store/4g0if6hqqm909mzm66zf6x4sjs39y1zz-system-manager`.
The shared attachment hook now compares the image, persistent unit path and
profile contents before reattaching. Both a hook-only deployment and a repeated
deployment preserved all seven portable PIDs and activation timestamps. Changed
native units still restart normally; unchanged images are still checked for
readiness and enabled/started when needed.

The first authorized reboot exposed native file-only resolver mounts reverting
to the host stub when resolved replaced its runtime files. Native applications
now bind a private resolver directory instead. After a second reboot, boot ID
`66473e04-fbaa-4a89-b291-014c5afd29b0`, all seven portable services started without
manual attachment/start commands, both SSH paths returned to the same machine,
all twelve application resolver contexts and both rootless container DNS paths
passed, and no units were failed. Applications were allowed to finish startup;
the runner automatically retried until Forgejo was ready. Syncthing's two peers
use Tailscale IPv6 primary connections, and all five folders are idle with zero
pending items or errors. All nine HTTPS routes, redirects and the original
certificate/ACME state remain intact. This supersedes the reboot limitations in
the individual migration checkpoints above.

The user confirmed passkey login. Backup restore/rollback exercises are deferred
at their request, and the minimal NixOS ARM builder is retained unchanged.
Certificate issuance has not been forced: a separate temporary Traefik instance
can use the same Unbound/Cloudflare DNS-01 path with Let's Encrypt's staging CA
and separate ACME storage, leaving production certificates and routes intact.
That would verify fresh issuance, rather than the existing certificate alone.
See [Traefik ACME configuration](https://github.com/traefik/traefik/blob/master/docs/content/reference/install-configuration/tls/certificate-resolvers/acme.md).

### Git push and CI acceptance (2026-10-18)

With explicit user approval, pushed existing commit `3fb6a9a` to temporary branch
`verification/mashu-20261018T211938Z` over Forgejo SSH23 and verified the remote
ref. Its [Gitleaks workflow](https://git.maxice8.com/max/ansible/actions/runs/746)
passed. Reran the existing [Infrastructure Checks workflow](https://git.maxice8.com/max/ansible/actions/runs/745)
on the same committed source: checkout, package downloads, Python lint/format,
bootstrap syntax, component mappings and actual Mashu Nix evaluation all passed
on the deployed rootless runner. The Nix evaluation step took eight seconds;
the persistent public-input cache was reused. No CI build or deployment was added.

Removed the temporary branch after both workflows succeeded and verified remote
master still points to `3fb6a9a`. No migration changes were committed or pushed;
these runs verify the current VPS's Git/CI operation against committed source,
not CI validation of the uncommitted migration changes. LFS was excluded by the
user, who will verify Pingvin upload/download and a fresh Syncthing transfer.

## Forgejo and runner

Preserve repositories, database, hook paths and SSH host keys. The Forgejo service
regenerates hooks against its selected Nix executable at startup. Public SSH23
redirects to its unprivileged 2222 listener; administrator OpenSSH stays on 22.

Create an instance runner registration token through Forgejo administration and
store it with `make secret service=forgejo-runner`. Existing `.runner` identity
is reused: rotating the registration token does not re-register that runner.
Do not delete an active identity merely to rotate an enrollment credential.

The runner agent accesses a dedicated rootless Podman API socket. Job storage is
disposable and separated from application data. Its systemd sandbox alone is not
a substitute for inspecting job containers. Validate a representative workflow
when changing the engine, runner version, labels or socket configuration.

## Tailscale

Initial enrollment uses a non-ephemeral auth key requesting `tag:server`. The
helper enables Tailscale SSH and accepts routes and tailnet DNS. Tailnet policy
must permit the tag and the `ubuntu` login. Store the key through
`make secret service=tailscale`; already-enrolled nodes reconcile preferences
without replacing their identity. Never clone the live node state into a VM.

Keep the independent key-only SSH22 path working before changing networking or
the Tailscale daemon. Tailscale owns its own packet-filter tables; the host
firewall deliberately owns only `inet hostfilter`.

On 2026-10-18, profile `/nix/store/g246h834icrin55kknhzfgm9bxysbsrs-system-manager`
removed UDP 21027 (Syncthing local discovery) from general host ingress. The
loopback/Tailscale allowances and TCP/UDP 22000 transfer ports remain intact.
Live rule inspection, both SSH paths, DNS and application health passed; both
Syncthing peers stayed connected over Tailscale IPv6. Tailscale and all twelve
application PIDs were unchanged. All application egress rules are unchanged;
ASF and CI retain broad public TCP/UDP access for their external workloads.

## Backrest and application recovery

Backrest's encrypted seed initializes a new installation; the UI-owned live
configuration persists in its data directory afterward. Changing the seed does
not overwrite an existing configuration. Preserve the repository identity,
retention/schedule and one `/var/lib/data` source. Changing repository credentials
requires checking the actual live configuration and access, not only editing the
seed. Do not put a mutable database backup under `/var/cache`.

The controlled capture service exports consistent database snapshots and briefly
stops coordinated writers when required. Do not start it as an incidental deploy
check. Stop the affected service before restoring its data; preserve ownership,
verify the restored identity/schema and then restart. Routine deployment does
not perform a backup or restore.

## Optional Ubuntu administration

Ubuntu owns APT updates, trim, base networking and OpenSSH. Automatic OS reboot
is disabled; schedule and verify reboots deliberately. Existing Ubuntu Pro/USG
reports and audit configuration are retained host administration, not installed
by the application bootstrap. `scripts/serve-usg-reports` can view retained reports
over an SSH tunnel; installed packages alone do not establish release support.
