# Run Pingvin's backend and frontend without an OCI runtime.
# Keep the database, uploads and custom images in the existing state directory.
{ pkgs, ... }:
let
  pingvin = pkgs.callPackage ../../pkgs/pingvin-share.nix { };
  hardening = import ../hardening.nix;
  common = hardening // {
    Restart = "on-failure";
    RestartSec = 5;
    TasksMax = 256;
    TimeoutStopSec = 45;
    RestrictAddressFamilies = [
      "AF_UNIX"
      "AF_INET"
      "AF_INET6"
    ];
    SocketBindDeny = [ "any" ];
  };
in
{
  environment.etc."nftables/pingvin-share.nft".source = ./firewall.nft;
  systemd.services.pingvin-share-network = import ../firewall.nix {
    inherit pkgs;
    name = "pingvin-share";
    policy = ./firewall.nft;
  };
  systemd.services.pingvin-share = {
    description = "Pingvin Share backend";
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-online.target" ];
    after = [
      "network-online.target"
      "userborn.service"
      "pingvin-share-network.service"
    ];
    requires = [ "pingvin-share-network.service" ];
    partOf = [ "pingvin-share-network.service" ];
    environment = {
      NODE_ENV = "production";
      BACKEND_HOST = "127.0.0.1";
      BACKEND_PORT = "3002";
      TRUST_PROXY = "true";
      DATA_DIRECTORY = "/var/lib/data/pingvin-share/data";
      DATABASE_URL = "file:/var/lib/data/pingvin-share/data/pingvin-share.db?connection_limit=1";
      IMAGES_DIRECTORY = "/var/lib/data/pingvin-share/images";
      CONFIG_FILE = "/var/lib/data/pingvin-share/config.yaml";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    };
    serviceConfig = common // {
      User = "pingvin-share";
      Group = "pingvin-share";
      # New images must be readable by the frontend's supplementary group.
      UMask = "0027";
      StateDirectory = [
        "data/pingvin-share"
        "data/pingvin-share/data"
      ];
      StateDirectoryMode = "0700";
      WorkingDirectory = "${pingvin}/backend";
      ExecStartPre = [
        # Keep shared images separate from private StateDirectory modes.
        "${pkgs.coreutils}/bin/install -d -m0750 /var/lib/data/pingvin-share/images"
        # Copy defaults without replacing custom images.
        "${pkgs.coreutils}/bin/cp -r --update=none ${pingvin}/frontend/public/img/. /var/lib/data/pingvin-share/images/"
        "${pkgs.coreutils}/bin/chmod -R g-s,g+rX /var/lib/data/pingvin-share/images"
        "${pingvin}/bin/pingvin-share-migrate"
        "${pingvin}/bin/pingvin-share-seed"
      ];
      ExecStart = "${pingvin}/bin/pingvin-share-backend";
      TimeoutStartSec = "5min";
      MemoryMax = "512M";
      SocketBindAllow = [ "ipv4:tcp:3002" ];
    };
  };
  systemd.services.pingvin-share-frontend = {
    description = "Pingvin Share frontend";
    wantedBy = [ "system-manager.target" ];
    after = [ "pingvin-share.service" ];
    requires = [ "pingvin-share.service" ];
    partOf = [ "pingvin-share.service" ];
    environment = {
      NODE_ENV = "production";
      HOSTNAME = "127.0.0.1";
      PORT = "3001";
      API_URL = "http://127.0.0.1:3002";
    };
    serviceConfig = common // {
      User = "pingvin-share-frontend";
      Group = "pingvin-share-frontend";
      SupplementaryGroups = [ "pingvin-share" ];
      WorkingDirectory = "${pingvin}/frontend";
      ExecStart = "${pingvin}/bin/pingvin-share-frontend";
      MemoryMax = "384M";
      SocketBindAllow = [ "ipv4:tcp:3001" ];
      BindReadOnlyPaths = [ "/var/lib/data/pingvin-share/images:${pingvin.frontend}/public/img" ];
      InaccessiblePaths = [
        "/var/lib/data/pingvin-share/data"
        "-/var/lib/data/pingvin-share/config.yaml"
      ];
      CacheDirectory = "pingvin-share-frontend";
      CacheDirectoryMode = "0700";
      BindPaths = [ "/var/cache/pingvin-share-frontend:${pingvin.frontend}/.next/cache" ];
      # Server rendering needs the backend. Block public frontend connections.
      IPAddressDeny = "any";
      IPAddressAllow = "localhost";
    };
  };
}
