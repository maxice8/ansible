# Host-local caching DNS forwarder; Ubuntu/resolved and Tailscale keep DNS ownership.
{ lib, pkgs, ... }:
let
  # Send tailnet names and reverse lookups to Tailscale at 100.100.100.100.
  # The range 100.64.0.0/10 has 64 DNS reverse zones.
  # https://tailscale.com/docs/reference/faq/dns-resolv-conf
  tailscaleZones = [
    "ts.net."
    "0.e.1.a.c.5.1.1.a.7.d.f.ip6.arpa."
  ]
  ++ lib.genList (index: "${toString (index + 64)}.100.in-addr.arpa.") 64;
  configFile = pkgs.writeText "unbound.conf" ''
    server:
      interface: 127.0.0.1
      port: 53
      do-ip4: yes
      do-ip6: no
      access-control: 127.0.0.0/8 allow
      username: ""
      chroot: ""
      directory: "/var/lib/unbound"
      pidfile: ""
      use-syslog: no
      hide-identity: yes
      hide-version: yes
      qname-minimisation: yes
      prefetch: yes
      cache-min-ttl: 60
      cache-max-ttl: 600
      auto-trust-anchor-file: "/var/lib/unbound/root.key"
      verbosity: 1
      # Private MagicDNS answers are unsigned and override default empty reverse zones.
      ${lib.concatMapStringsSep "\n" (zone: ''
        domain-insecure: "${zone}"
        local-zone: "${zone}" transparent
      '') tailscaleZones}

    forward-zone:
      name: "."
      forward-tcp-upstream: yes
      forward-first: no
      forward-addr: 9.9.9.9
      forward-addr: 8.8.8.8
      forward-addr: 208.67.222.222

    ${lib.concatMapStringsSep "\n" (zone: ''
      forward-zone:
        name: "${zone}"
        forward-tcp-upstream: yes
        forward-first: no
        forward-addr: 100.100.100.100
    '') tailscaleZones}
  '';
in
{
  environment.etc."unbound/unbound.conf".source = configFile;
  environment.etc."nftables/unbound.nft".source = ./firewall.nft;
  systemd.services.unbound-network = import ../firewall.nix {
    inherit pkgs;
    name = "unbound";
    policy = ./firewall.nft;
  };
  systemd.services.unbound = {
    description = "Host-local Unbound caching DNS forwarder";
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    after = [
      "network-online.target"
      "userborn.service"
      "unbound-network.service"
      "tailscaled.service"
    ];
    requires = [ "unbound-network.service" ];
    partOf = [ "unbound-network.service" ];
    restartTriggers = [ configFile ];
    preStart = ''
      # Seed once from the pinned package; retain RFC 5011 trust-anchor updates.
      if [ ! -s /var/lib/unbound/root.key ]; then
        ${pkgs.coreutils}/bin/install -m 0644 ${pkgs.dns-root-data}/root.key /var/lib/unbound/root.key
      fi
      ${pkgs.unbound}/bin/unbound-checkconf /etc/unbound/unbound.conf
    '';
    serviceConfig = import ../hardening.nix // {
      User = "unbound";
      Group = "unbound";
      StateDirectory = "unbound";
      StateDirectoryMode = "0700";
      ExecStart = "${pkgs.unbound}/bin/unbound -d -p -c /etc/unbound/unbound.conf";
      Restart = "on-failure";
      RestartSec = 5;
      CapabilityBoundingSet = "CAP_NET_BIND_SERVICE";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      # Unbound/checkconf use getifaddrs (netlink) even for numeric listeners.
      RestrictAddressFamilies = [
        "AF_UNIX"
        "AF_INET"
        "AF_NETLINK"
      ];
      MemoryDenyWriteExecute = true;
      # Permit port zero for outbound TCP; only DNS may bind a named port.
      SocketBindDeny = [
        "ipv4:tcp:1-65535"
        "ipv6:tcp:1-65535"
        "ipv4:udp:1-65535"
        "ipv6:udp:1-65535"
      ];
      SocketBindAllow = [
        "ipv4:tcp:53"
        "ipv4:udp:53"
      ];
      MemoryMax = "256M";
      TasksMax = 64;
    };
  };
}
