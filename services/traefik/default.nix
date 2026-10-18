# Run Traefik in a service image. Keep certificates and credentials outside the image.
# Apply its network policy on the host.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  settings = import ./settings.nix;
  traefik = pkgs.callPackage ../../pkgs/traefik.nix { };
  hardening = import ../hardening.nix;
  staticConfig = pkgs.writeText "traefik-static.json" (builtins.toJSON settings.static);
  # The file provider requires a .yaml/.toml filename; JSON is valid YAML.
  routes = pkgs.writeText "traefik-routes.yaml" (builtins.toJSON settings.dynamic);
  unitSettings = {
    Unit = {
      Description = "Traefik portable service";
      Wants = [
        "network-online.target"
      ];
      After = [
        "network-online.target"
        "userborn.service"
        "sops-install-secrets.service"
        "traefik-network.service"
      ];
      Requires = [
        "sops-install-secrets.service"
        "traefik-network.service"
      ];
      PartOf = [
        "traefik-network.service"
      ];
    };
    Service = hardening // {
      Environment = [
        "CF_DNS_API_TOKEN_FILE=/run/credentials/traefik.service/cloudflare-token"
        "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
      ];
      User = "5002";
      Group = "5002";
      StateDirectory = "data/traefik";
      StateDirectoryMode = "0700";
      LoadCredential = [ "cloudflare-token:${config.sops.secrets.cloudflare-dns-token.path}" ];
      ExecStart = "${traefik}/bin/traefik --configFile=${staticConfig}";
      Restart = "on-failure";
      RestartSec = 5;
      MemoryMax = "256M";
      TasksMax = 128;
      # Only the public low ports require this capability.
      CapabilityBoundingSet = "CAP_NET_BIND_SERVICE";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      IPAddressDeny = [
        "169.254.0.0/16"
        "fe80::/10"
      ];
      # Go probes IPv6 by binding port 0. Deny named ports while permitting that probe;
      # port-0 listeners still need the host firewall's ingress restrictions.
      SocketBindDeny = [
        "ipv4:tcp:1-65535"
        "ipv6:tcp:1-65535"
        "ipv4:udp:1-65535"
        "ipv6:udp:1-65535"
      ];
      SocketBindAllow = [
        "ipv4:tcp:80"
        "ipv6:tcp:80"
        "ipv4:tcp:443"
        "ipv6:tcp:443"
        "ipv4:tcp:9080"
      ];
    };
    Install.WantedBy = "system-manager.target";
  };
  unit = pkgs.writeText "traefik.service" (
    lib.generators.toINI { listsAsDuplicateKeys = true; } unitSettings
  );
  image = pkgs.portableService {
    pname = "traefik";
    version = traefik.version;
    description = "Mashu Traefik";
    units = [ unit ];
    symlinks = [
      {
        object = routes;
        symlink = "etc/traefik/routes.yaml";
      }
      # Pre-create the host state mountpoint in the read-only image.
      {
        object = unit;
        symlink = "var/lib/data/traefik/.image-unit";
      }
    ];
  };
in
{
  system-manager.preActivationAssertions.traefikIdentity = {
    enable = true;
    # Refuse to adopt a different account's UID/GID or an existing mismatched name.
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 5002 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != traefik ]; then
          echo "Traefik UID/GID 5002 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" traefik || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 5002 ]; then
          echo "Existing Traefik account has a different UID/GID" >&2; exit 1
        fi
      done
    '';
  };
  services.userborn.enable = lib.mkForce true;
  # Force whole account sets to discard NixOS's Ubuntu-incompatible default users.
  # Other service modules may merge their own mkForce entries at the same priority.
  users.users = lib.mkForce {
    traefik = {
      isSystemUser = true;
      uid = 5002;
      group = "traefik";
      shell = "/usr/sbin/nologin";
    };
  };
  users.groups = lib.mkForce { traefik.gid = 5002; };

  sops.secrets.cloudflare-dns-token = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "cloudflare_dns_api_token";
    restartUnits = [ "traefik.service" ];
  };

  environment.etc."nftables/traefik.nft".source = ./firewall.nft;
  systemd.services.traefik-network = import ../firewall.nix {
    inherit pkgs;
    name = "traefik";
    policy = ./firewall.nft;
  };
  systemd.services.traefik = import ../portable.nix {
    inherit image;
    name = "traefik";
    settings = unitSettings;
  };
}
