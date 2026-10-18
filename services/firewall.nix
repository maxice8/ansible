# UID-scoped firewall unit shared by native apps and isolated container runtimes.
# Public peer ports may vary; private/host destinations require explicit local ports.
{ pkgs, name, uid, localTCP ? [], localUDP ? [], publicTCP ? [ 443 ], publicUDP ? [] }:
let
  lib = pkgs.lib;
  # Keep existing table names so updates replace the same rules.
  table = "${builtins.replaceStrings [ "-" ] [ "_" ] name}_egress";
  ports = xs: lib.concatMapStringsSep ", " toString xs;
  rule = family: address: protocol: allowed:
    lib.optionalString (allowed != []) "meta skuid ${toString uid} ${family} daddr ${address} ${protocol} dport { ${ports allowed} } accept";
  publicRule = protocol: allowed:
    if allowed == null then "meta skuid ${toString uid} meta l4proto ${protocol} accept"
    else lib.optionalString (allowed != []) "meta skuid ${toString uid} ${protocol} dport { ${ports allowed} } accept";
  policy = pkgs.writeText "${name}-firewall.nft" ''
    destroy table inet ${table}
    table inet ${table} {
      chain output {
        type filter hook output priority filter; policy accept;
        meta skuid ${toString uid} ct state established,related accept
        meta skuid ${toString uid} ip daddr 127.0.0.1 meta l4proto { tcp, udp } th dport 53 accept
        ${rule "ip" "127.0.0.1" "tcp" localTCP}
        ${rule "ip6" "::1" "tcp" localTCP}
        ${rule "ip" "127.0.0.1" "udp" localUDP}
        meta skuid ${toString uid} fib daddr type local reject
        meta skuid ${toString uid} ip daddr { 0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, 172.16.0.0/12, 192.168.0.0/16, 224.0.0.0/4, 240.0.0.0/4 } reject
        meta skuid ${toString uid} ip6 daddr { ::/128, ::1/128, fc00::/7, fe80::/10, ff00::/8 } reject
        ${publicRule "tcp" publicTCP}
        ${publicRule "udp" publicUDP}
        meta skuid ${toString uid} reject
      }
    }
  '';
in {
  wantedBy = [ "system-manager.target" ];
  before = [ "${name}.service" ];
  serviceConfig = import ./hardening.nix // {
    Type = "oneshot"; RemainAfterExit = true;
    CapabilityBoundingSet = "CAP_NET_ADMIN";
    ExecStart = "${pkgs.nftables}/bin/nft -f ${policy}";
    ExecStop = "${pkgs.nftables}/bin/nft destroy table inet ${table}";
  };
}
