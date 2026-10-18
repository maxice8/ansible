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
