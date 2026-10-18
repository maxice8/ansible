# Exercise both real proxy units with a local synthetic OIDC issuer and credentials.
# Reuse the ingress fixture; no live DNS, identity provider or secrets enter the VM.
{ source, secretFile }:
import ./traefik-profile.nix {
  inherit source secretFile;
  extraModules = [
    ../services/pomerium.nix
    ({ lib, pkgs, ... }: {
      sops.secrets = builtins.listToAttrs (map (name: {
        name = "pomerium-${name}";
        value.sopsFile = lib.mkForce
          (builtins.path { path = builtins.toPath secretFile; name = "pomerium-fixture.sops.yaml"; });
      }) [ "cookie-secret" "shared-secret" "idp-client-id" "idp-client-secret" ]);
      environment.etc."pomerium/config.yaml".text = lib.mkForce (builtins.toJSON (
        (import ../services/pomerium-settings.nix) // { idp_provider_url = "http://127.0.0.1:1411"; }
      ));
      # Only the disposable issuer needs this additional loopback destination.
      systemd.services.pomerium-network.serviceConfig.ExecStart = lib.mkForce
        (let policy = builtins.replaceStrings
          [ "1242, 5443" ] [ "443, 1242, 1411, 5443" ]
          (builtins.readFile ../services/pomerium-egress.nft);
          file = pkgs.writeText "pomerium-fixture-egress.nft" policy;
        in "${pkgs.nftables}/bin/nft -f ${file}");
    })
  ];
}
