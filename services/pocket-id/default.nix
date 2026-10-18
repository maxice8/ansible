# Native passkey/OIDC provider: Nix owns execution, Pocket ID owns its SQLite/UI settings.
# Keep the issuer hostname and encryption key stable: both protect existing login identities.
{ config, lib, pkgs, ... }:
let
  pocket-id = pkgs.callPackage ../../pkgs/pocket-id.nix {};
  hardening = import ../hardening.nix;
in {
  system-manager.preActivationAssertions.pocketIdIdentity = {
    enable = true;
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 5004 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != pocket-id ]; then
          echo "Pocket ID UID/GID 5004 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" pocket-id || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 5004 ]; then
          echo "Existing Pocket ID account has a different UID/GID" >&2; exit 1
        fi
      done
    '';
  };
  services.userborn.enable = lib.mkForce true;
  # Equal-priority mkForce account sets merge across our service modules.
  users.users = lib.mkForce {
    pocket-id = { isSystemUser = true; uid = 5004; group = "pocket-id"; shell = "/usr/sbin/nologin"; };
  };
  users.groups = lib.mkForce { pocket-id.gid = 5004; };
  sops.secrets.pocket-id-encryption-key = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "pocket_id_encryption_key";
    restartUnits = [ "pocket-id.service" ];
  };
  systemd.services.pocket-id-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "pocket-id.service" ];
    serviceConfig = hardening // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./firewall.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet pocket_id_egress";
    };
  };
  systemd.services.pocket-id = {
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "pocket-id-network.service" ];
    requires = [ "sops-install-secrets.service" "pocket-id-network.service" ];
    partOf = [ "pocket-id-network.service" ];
    environment = {
      APP_URL = "https://id.maxice8.com";
      HOST = "127.0.0.1"; PORT = "1411";
      # The embedded Francis task runtime otherwise binds a wildcard UDP socket.
      ACTORS_HOST = "127.0.0.1"; ACTORS_PORT = "1414";
      TRUST_PROXY = "127.0.0.1/32";
      DB_CONNECTION_STRING = "/var/lib/data/pocket-id/pocket-id.db";
      UPLOAD_PATH = "/var/lib/data/pocket-id/uploads";
      GEOLITE_DB_PATH = "/var/lib/data/pocket-id/GeoLite2-City.mmdb";
      ENCRYPTION_KEY_FILE = "/run/credentials/pocket-id.service/encryption-key";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      VERSION_CHECK_DISABLED = "true";
      ANALYTICS_DISABLED = "true";
    };
    serviceConfig = hardening // {
      User = "pocket-id"; Group = "pocket-id";
      StateDirectory = "data/pocket-id"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/pocket-id";
      LoadCredential = [ "encryption-key:${config.sops.secrets.pocket-id-encryption-key.path}" ];
      ExecStart = "${pocket-id}/bin/pocket-id";
      Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "512M"; TasksMax = 128;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      LockPersonality = true; SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      # Allow port zero for outbound UDP and Go family probes, plus only named listeners.
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:1411" "ipv4:udp:1414" ];
    };
  };
}
