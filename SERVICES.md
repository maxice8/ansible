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

Argus configuration is generated by `services/argus.nix`. It compares upstream
releases with package versions selected by Nix; Forgejo and Netdata additionally
have runtime HTTP version probes. Its dashboard is read-only except for release
approval/skipping state. Approval does not update Git or deploy a package.

`make secret service=argus` accepts a read-only public GitHub token and a complete
Discord webhook URL, storing the webhook ID/token separately. Deploy the change,
then verify delivery before revoking old credentials. Update packages through
`make update`, review/build them and explicitly deploy; no GitOps controller runs.

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
