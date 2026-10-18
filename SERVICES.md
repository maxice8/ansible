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
| Tailscale | `tailscale_auth_key` | `tailscale` (node/SSH identity) |

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
