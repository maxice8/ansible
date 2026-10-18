# Host-local caching DNS forwarder; Ubuntu/resolved and Tailscale keep DNS ownership.
{ pkgs, ... }:
let
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

    forward-zone:
      name: "."
      forward-tcp-upstream: yes
      forward-first: no
      forward-addr: 9.9.9.9
      forward-addr: 8.8.8.8
      forward-addr: 208.67.222.222
  '';
in {
  environment.etc."unbound/unbound.conf".source = configFile;
  systemd.services.unbound-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "unbound.service" ];
    serviceConfig = import ../hardening.nix // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./firewall.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet unbound_egress";
    };
  };
  systemd.services.unbound = {
    description = "Host-local Unbound caching DNS forwarder";
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" "userborn.service" "unbound-network.service" ];
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
      User = "unbound"; Group = "unbound";
      StateDirectory = "unbound"; StateDirectoryMode = "0700";
      ExecStart = "${pkgs.unbound}/bin/unbound -d -p -c /etc/unbound/unbound.conf";
      Restart = "on-failure"; RestartSec = 5;
      CapabilityBoundingSet = "CAP_NET_BIND_SERVICE";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      # Unbound/checkconf use getifaddrs (netlink) even for numeric listeners.
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_NETLINK" ];
      MemoryDenyWriteExecute = true; LockPersonality = true;
      SystemCallArchitectures = "native";
      # Permit port zero for outbound TCP; only DNS may bind a named port.
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:53" "ipv4:udp:53" ];
      MemoryMax = "256M"; TasksMax = 64;
    };
  };
}
