# Run Pocket ID in a service image. Keep its database and uploads outside the image.
# Preserve the issuer hostname and encryption key on upgrades.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  pocket-id = pkgs.pocket-id;
  hardening = import ../hardening.nix;
  environment = {
    APP_URL = "https://id.maxice8.com";
    HOST = "127.0.0.1";
    PORT = "1411";
    # The embedded Francis task runtime otherwise binds a wildcard UDP socket.
    ACTORS_HOST = "127.0.0.1";
    ACTORS_PORT = "1414";
    TRUST_PROXY = "127.0.0.1/32";
    DB_CONNECTION_STRING = "/var/lib/data/pocket-id/pocket-id.db";
    UPLOAD_PATH = "/var/lib/data/pocket-id/uploads";
    GEOLITE_DB_PATH = "/var/lib/data/pocket-id/GeoLite2-City.mmdb";
    ENCRYPTION_KEY_FILE = "/run/credentials/pocket-id.service/encryption-key";
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    VERSION_CHECK_DISABLED = "true";
    ANALYTICS_DISABLED = "true";
  };

  unitSettings = {
    Unit = {
      Description = "Pocket ID portable service";
      Wants = [
        "network-online.target"
      ];
      After = [
        "network-online.target"
        "userborn.service"
        "sops-install-secrets.service"
        "pocket-id-network.service"
      ];
      Requires = [
        "sops-install-secrets.service"
        "pocket-id-network.service"
      ];
      PartOf = [
        "pocket-id-network.service"
      ];
    };
    Service = hardening // {
      # Preserve the host identity used by existing state and firewall rules.
      User = "5004";
      Group = "5004";
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      StateDirectory = "data/pocket-id";
      StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/pocket-id";
      LoadCredential = [ "encryption-key:${config.sops.secrets.pocket-id-encryption-key.path}" ];
      ExecStart = "${pocket-id}/bin/pocket-id";
      Restart = "on-failure";
      RestartSec = 5;
      MemoryMax = "512M";
      TasksMax = 128;
      RestrictAddressFamilies = [
        "AF_UNIX"
        "AF_INET"
        "AF_INET6"
        "AF_NETLINK"
      ];
      IPAddressDeny = [
        "169.254.0.0/16"
        "fe80::/10"
      ];
      # Allow port zero for outbound UDP and Go family probes, plus only named listeners.
      SocketBindDeny = [
        "ipv4:tcp:1-65535"
        "ipv6:tcp:1-65535"
        "ipv4:udp:1-65535"
        "ipv6:udp:1-65535"
      ];
      SocketBindAllow = [
        "ipv4:tcp:1411"
        "ipv4:udp:1414"
      ];
    };
    Install.WantedBy = "system-manager.target";
  };
  unit = pkgs.writeText "pocket-id.service" (
    lib.generators.toINI { listsAsDuplicateKeys = true; } unitSettings
  );
  image = pkgs.portableService {
    pname = "pocket-id";
    version = pocket-id.version;
    description = "Mashu Pocket ID";
    units = [ unit ];
    # Pre-create the host state mountpoint in the read-only image.
    symlinks = [
      {
        object = unit;
        symlink = "var/lib/data/pocket-id/.image-unit";
      }
    ];
  };
in
{
  sops.secrets.pocket-id-encryption-key = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "pocket_id_encryption_key";
    restartUnits = [ "pocket-id.service" ];
  };
  environment.etc."nftables/pocket-id.nft".source = ./firewall.nft;
  systemd.services.pocket-id-network = import ../firewall.nix {
    inherit pkgs;
    name = "pocket-id";
    policy = ./firewall.nft;
  };
  systemd.services.pocket-id = import ../portable.nix {
    inherit image;
    name = "pocket-id";
    settings = unitSettings;
  };
}
