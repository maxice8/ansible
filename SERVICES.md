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

`services/unbound/default.nix` declares a hardened host-local resolver on `127.0.0.1:53`
for UDP and TCP clients. It forwards uncached queries over TCP port 53 to
`9.9.9.9`, `8.8.8.8` or `208.67.222.222`, matching the work Ansible setup.
Its dedicated UID 62010 can contact only those upstream DNS endpoints and reply
to clients. DNSSEC trust anchors are seeded from pinned Nix root data and updated
in `/var/lib/unbound`; the response cache is disposable. Upstream DNS uses plain
TCP, not TLS. No public DNS listener or ingress allowance is added.

This first step adds the service only. Ubuntu's `systemd-resolved`, Tailscale DNS,
application resolver settings and container DNS remain unchanged. Applications
still use their existing DNS paths until a separate resolver cutover; containers
will need a reachable endpoint rather than the host's loopback address.

The read-only VPS check (`make test`) queries the deployed resolver over both UDP
and TCP, using its real upstreams. It does not change application DNS settings.

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

## Pocket ID and Pomerium

Keep Pocket ID's canonical issuer `https://id.maxice8.com` stable. Create or retain
the Pomerium OIDC client with its exact callback URL shown by the provider. Store
client/cookie/shared credentials through `make secret service=pomerium`. Preserve
its databroker directory when maintaining existing sessions.

Test a real passkey login and protected-application redirect after identity or
OIDC changes. Loopback readiness checks alone do not exercise a browser login.

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

Nix supplies `bin/activate-portables` in the built host profile. After activating
the host configuration, `deploy.py` runs this script over SSH: it attaches a fresh
installation or uses `portablectl reattach --now` to replace the current image
and restart Argus. It then enables the unit through host `systemctl`, creating
the normal boot dependency. `make deploy` remains the complete deployment command.
The script and image are retained by the Nix profile for reproducibility and
rollback. Calling System Manager directly does not run this extra deployment step.

The Nix-declared `mashu` portable profile exposes machine identity, host DNS and
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
immutable image paths, and repeat deployment all passed. Only `argus` appears in
the portable inventory, its normal systemd boot link is enabled, and all 11
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

### Remaining portable candidates, simplest first

This ranks packaging effort. Authentication and ingress services have a larger
outage impact even when their image is simple; migrate one application at a time.

| Order | Service | Main work beyond the Argus pattern |
| --- | --- | --- |
| 1 | Pocket ID | One binary, SQLite/uploads and a runtime encryption key; verify existing passkeys and OIDC clients. |
| 2 | Traefik | One binary and config, ACME state, DNS credential and low-port capability; validate public ingress and certificate renewal. |
| 3 | Syncthing | Bind synchronized folders and identity/config state; verify peer connections, discovery and real transfers. |
| 4 | ArchiSteamFarm | Include .NET and UI assets, preserve bot state and allow JIT; verify Steam connectivity without parallel bot sessions. |
| 5 | Pomerium | Embedded Envoy, executable temporary files and internal RPC listeners; verify login, callbacks and existing sessions. |
| 6 | Forgejo | Git/LFS/SSH and helper closure, generated hooks, repository/database state; verify push, clone, SSH and jobs. |

Keep Unbound, Tailscale, Netdata, Backrest, the Forgejo runner and its Podman
engine native for their host/network/data/socket integration. Keep Pingvin Share X
on its pinned upstream OCI image. Firewalls, accounts, SOPS and maintenance units
also remain host services.

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
