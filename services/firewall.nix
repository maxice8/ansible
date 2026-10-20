# Load a service's installed nftables policy. Each service owns one table.
{
  pkgs,
  name,
  policy,
}:
let
  table = "${builtins.replaceStrings [ "-" ] [ "_" ] name}_egress";
in
{
  wantedBy = [ "system-manager.target" ];
  before = [ "${name}.service" ];
  restartTriggers = [ policy ];
  serviceConfig = import ./hardening.nix // {
    Type = "oneshot";
    RemainAfterExit = true;
    CapabilityBoundingSet = "CAP_NET_ADMIN";
    ExecStart = "${pkgs.nftables}/bin/nft -f /etc/nftables/${name}.nft";
    ExecReload = "${pkgs.nftables}/bin/nft -f /etc/nftables/${name}.nft";
    ExecStop = "${pkgs.nftables}/bin/nft destroy table inet ${table}";
  };
}
