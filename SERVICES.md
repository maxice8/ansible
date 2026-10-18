# Service setup and credentials

Nix declares service configuration; durable application state lives under `/var/lib/data`.

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

## Tailscale

Initial enrollment uses a non-ephemeral auth key requesting `tag:server`. The
helper enables Tailscale SSH and accepts routes and tailnet DNS. Tailnet policy
must permit the tag and the `ubuntu` login. Store the key through
`make secret service=tailscale`; already-enrolled nodes reconcile preferences
without replacing their identity. Never clone the live node state into a VM.

Keep the independent key-only SSH22 path working before changing networking or
the Tailscale daemon. Tailscale owns its own packet-filter tables; the host
firewall deliberately owns only `inet hostfilter`.

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

## Pocket ID and Pomerium

Keep Pocket ID's canonical issuer `https://id.maxice8.com` stable. Create or retain
the Pomerium OIDC client with its exact callback URL shown by the provider. Store
client/cookie/shared credentials through `make secret service=pomerium`. Preserve
its databroker directory when maintaining existing sessions.

Test a real passkey login and protected-application redirect after identity or
OIDC changes. Loopback readiness checks alone do not exercise a browser login.

## Syncthing

| Service | Image | State and special runtime requirements |
| --- | --- | --- |
| Syncthing 2.1.6 | `syncthing.raw` | UID/GID 5001; device keys, index and all five synchronized folders stay under `/var/lib/data/syncthing`. The host heartbeat remains native. New synchronized folders must be inside that state root to be visible in the image. |

## Forgejo

| Service | Image | State and special runtime requirements |
| --- | --- | --- |
| Forgejo 17.0.0 | `forgejo.raw` | UID/GID 5005; database, repositories, LFS and SSH host keys remain under `/var/lib/data/forgejo`. The image includes Git/LFS/SSH, signing/compression helpers, `/bin/sh`, `/usr/bin/env` and a minimal Forgejo account database for subprocesses. |

## ArchiSteamFarm

| Service | Image | State and special runtime requirements |
| --- | --- | --- |
| ArchiSteamFarm 6.3.10.6 | `archisteamfarm.raw` | UID/GID 5013; bot configuration/session state remains under `/var/lib/data/archisteamfarm`. The image includes .NET, plugins and the UI, preserving its state-directory symlink. JIT and executable private temporary files remain allowed. |

## Pomerium

| Service | Image | State and special runtime requirements |
| --- | --- | --- |
| Pomerium 0.33.4 | `pomerium.raw` | UID/GID 5003; the original databroker persists, and four credentials enter through `LoadCredential`. Embedded Envoy uses Nix glibc via conventional loader paths, executable private temporary files and the existing loopback RPC range. |

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

## Pingvin Share X

The pinned upstream OCI image runs under a dedicated rootless identity.
Persistent state lives under `/var/lib/data/pingvin-share`; runtime images are disposable.

## Netdata

The host collector runs without privileged plugin wrappers or a Docker socket.
Discord notifications and heartbeat URLs are supplied as systemd credentials.
