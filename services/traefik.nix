# Native Traefik, its isolated state/credential, and a narrowly scoped egress policy.
# Ubuntu accounts are preserved: userborn receives only explicitly owned identities.
{ config, lib, pkgs, ... }:
let
  settings = import ./traefik-settings.nix;
  traefik = pkgs.callPackage ../pkgs/traefik.nix {};
in {
  system-manager.preActivationAssertions.traefikIdentity = {
    enable = true;
    # Refuse to adopt a different account's UID/GID or an existing mismatched name.
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 62002 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != traefik ]; then
          echo "Traefik UID/GID 62002 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" traefik || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 62002 ]; then
          echo "Existing Traefik account has a different UID/GID" >&2; exit 1
        fi
      done
    '';
  };
  services.userborn.enable = lib.mkForce true;
  # Force whole account sets to discard NixOS's Ubuntu-incompatible default users.
  # Other service modules may merge their own mkForce entries at the same priority.
  users.users = lib.mkForce {
    traefik = { isSystemUser = true; uid = 62002; group = "traefik"; shell = "/usr/sbin/nologin"; };
  };
  users.groups = lib.mkForce { traefik.gid = 62002; };

  sops.secrets.cloudflare-dns-token = {
    sopsFile = ../secrets/mashu.sops.yaml;
    key = "cloudflare_dns_api_token";
    restartUnits = [ "traefik.service" ];
  };
  environment.etc."traefik/static.json".text = builtins.toJSON settings.static;
  # JSON is valid YAML; the file provider requires a .yaml/.toml filename.
  environment.etc."traefik/routes.yaml".text = builtins.toJSON settings.dynamic;

  systemd.services.traefik-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "traefik.service" ];
    serviceConfig = import ./hardening.nix // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./traefik-egress.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet traefik_egress";
    };
  };
  systemd.services.traefik = {
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    # Nix replaces config symlinks; restart explicitly rather than relying on inotify.
    restartTriggers = [
      config.environment.etc."traefik/static.json".source
      config.environment.etc."traefik/routes.yaml".source
    ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "traefik-network.service" ];
    requires = [ "sops-install-secrets.service" "traefik-network.service" ];
    # Restart the proxy with its policy; account creation needs ordering only.
    partOf = [ "traefik-network.service" ];
    environment = {
      CF_DNS_API_TOKEN_FILE = "/run/credentials/traefik.service/cloudflare-token";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    };
    serviceConfig = import ./hardening.nix // {
      User = "traefik"; Group = "traefik";
      StateDirectory = "data/traefik"; StateDirectoryMode = "0700";
      LoadCredential = [ "cloudflare-token:${config.sops.secrets.cloudflare-dns-token.path}" ];
      ExecStart = "${traefik}/bin/traefik --configFile=/etc/traefik/static.json";
      Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "256M"; TasksMax = 128;
      # Only the final public low ports require this capability.
      CapabilityBoundingSet = "CAP_NET_BIND_SERVICE";
      AmbientCapabilities = "CAP_NET_BIND_SERVICE";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      # Go probes IPv6 by binding port 0. Deny named ports while permitting that probe;
      # port-0 listeners still need the host firewall's ingress restrictions.
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:80" "ipv6:tcp:80" "ipv4:tcp:443" "ipv6:tcp:443" "ipv4:tcp:9080" ];
    };
  };
}
