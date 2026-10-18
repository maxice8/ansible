# Native Pomerium with private credentials/state and a separate privileged egress unit.
# The embedded Envoy needs executable private /tmp and loopback ephemeral RPC ports.
{ config, lib, pkgs, ... }:
let
  pomerium = pkgs.callPackage ../pkgs/pomerium.nix {};
  credentials = [ "cookie-secret" "shared-secret" "idp-client-id" "idp-client-secret" ];
in {
  system-manager.preActivationAssertions.pomeriumIdentity = {
    enable = true;
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 62003 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != pomerium ]; then
          echo "Pomerium UID/GID 62003 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" pomerium || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 62003 ]; then
          echo "Existing Pomerium account has a different UID/GID" >&2; exit 1
        fi
      done
      # Upstream's automatic internal listeners must fit our explicit bind/egress range.
      read -r first last < /proc/sys/net/ipv4/ip_local_port_range
      test "$first" = 32768 && test "$last" = 60999
    '';
  };
  services.userborn.enable = lib.mkForce true;
  # Merge only explicitly owned accounts, preserving Ubuntu's existing identities.
  users.users = lib.mkForce {
    pomerium = { isSystemUser = true; uid = 62003; group = "pomerium"; shell = "/usr/sbin/nologin"; };
  };
  users.groups = lib.mkForce { pomerium.gid = 62003; };
  # map creates one SOPS secret per credential; replaceStrings maps filenames to keys.
  sops.secrets = builtins.listToAttrs (map (name: {
    name = "pomerium-${name}";
    value = {
      sopsFile = ../secrets/mashu.sops.yaml;
      key = "pomerium_${builtins.replaceStrings [ "-" ] [ "_" ] name}";
      restartUnits = [ "pomerium.service" ];
    };
  }) credentials);
  environment.etc."pomerium/config.yaml".text = builtins.toJSON (import ./pomerium-settings.nix);
  systemd.services.pomerium-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "pomerium.service" ];
    serviceConfig = import ./hardening.nix // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./pomerium-egress.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet pomerium_egress";
    };
  };
  systemd.services.pomerium = {
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "pomerium-network.service" ];
    requires = [ "sops-install-secrets.service" "pomerium-network.service" ];
    partOf = [ "pomerium-network.service" ];
    restartTriggers = [ config.environment.etc."pomerium/config.yaml".source ];
    environment = {
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      COOKIE_SECRET_FILE = "/run/credentials/pomerium.service/cookie-secret";
      SHARED_SECRET_FILE = "/run/credentials/pomerium.service/shared-secret";
      IDP_CLIENT_SECRET_FILE = "/run/credentials/pomerium.service/idp-client-secret";
      # Bound Envoy's concurrency on hosts with many visible CPUs.
      GOMAXPROCS = "2";
    };
    # Client ID has no *_FILE option; it is public, but keep its source credential private.
    script = ''
      export IDP_CLIENT_ID="$(< "$CREDENTIALS_DIRECTORY/idp-client-id")"
      exec ${pomerium}/bin/pomerium -config /etc/pomerium/config.yaml
    '';
    serviceConfig = import ./hardening.nix // {
      User = "pomerium"; Group = "pomerium";
      StateDirectory = "data/pomerium"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/pomerium";
      LoadCredential = map (name: "${name}:${config.sops.secrets."pomerium-${name}".path}") credentials;
      Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "512M"; TasksMax = 128;
      ProtectKernelLogs = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      RestrictNamespaces = true; RestrictRealtime = true; LockPersonality = true;
      SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      # Port zero supports Go's probes; upstream also binds allocated ephemeral ports.
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:8080" "ipv4:tcp:5443" "ipv4:tcp:28080" "ipv4:tcp:32768-60999" "ipv6:tcp:32768-60999" ];
    };
  };
}
