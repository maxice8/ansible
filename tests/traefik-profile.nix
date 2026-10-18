# Exercise the actual native ingress module with synthetic secrets and TLS in a VM.
# Real DNS challenges are disabled here; live staging-CA acceptance is a separate check.
{ source, secretFile, extraModules ? [] }:
let
  inputs = (builtins.getFlake "path:${source}").inputs;
  settings = import ../services/traefik-settings.nix;
  # Traefik rejects a present-but-empty resolver map; omit it entirely in the VM.
  static = builtins.removeAttrs settings.static [ "certificatesResolvers" ] // {
    entryPoints = settings.static.entryPoints // {
      websecure = {
        address = ":443";
        http = { aliasHeadersStrategy = "reject"; tls.options = "default"; };
      };
    };
  };
  dynamic = settings.dynamic // {
    tls = settings.dynamic.tls // {
      certificates = [{
        certFile = "/var/lib/data/traefik/test-cert.pem";
        keyFile = "/var/lib/data/traefik/test-key.pem";
      }];
    };
  };
in inputs.system-manager.lib.makeSystemConfig {
  specialArgs = { inherit inputs; };
  modules = [
    ../services/base.nix
    ../services/traefik.nix
    ({ lib, ... }: {
      nixpkgs.hostPlatform = "aarch64-linux";
      sops.secrets.cloudflare-dns-token.sopsFile = lib.mkForce
        (builtins.path { path = builtins.toPath secretFile; name = "cloudflare-fixture.sops.yaml"; });
      environment.etc."traefik/static.json".text = lib.mkForce (builtins.toJSON static);
      environment.etc."traefik/routes.yaml".text = lib.mkForce (builtins.toJSON dynamic);
      system-manager.preActivationAssertions.fixtureHost = {
        enable = true;
        script = ''test "$(/usr/bin/hostname)" = mashu-test'';
      };
    })
  ] ++ extraModules;
}
