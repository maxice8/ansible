# Service setup and credentials

Nix declares service configuration; durable application state lives under `/var/lib/data`.

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
