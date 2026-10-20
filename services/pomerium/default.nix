# Run Pomerium in a service image. Keep credentials and state outside the image.
# Envoy needs executable temporary files and dynamic loopback RPC ports.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  pomerium = pkgs.pomerium;
  credentials = [
    "cookie-secret"
    "shared-secret"
    "idp-client-id"
    "idp-client-secret"
  ];
  hardening = import ../hardening.nix;
  environment = {
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    COOKIE_SECRET_FILE = "/run/credentials/pomerium.service/cookie-secret";
    SHARED_SECRET_FILE = "/run/credentials/pomerium.service/shared-secret";
    IDP_CLIENT_SECRET_FILE = "/run/credentials/pomerium.service/idp-client-secret";
    # Bound Envoy's concurrency on hosts with many visible CPUs.
    GOMAXPROCS = "2";
  };
  configFile = pkgs.writeText "pomerium-config.yaml" (builtins.toJSON (import ./settings.nix));
  # Upstream has no *_FILE option for the client ID.
  start = pkgs.writeShellScript "pomerium-start" ''
    set -euo pipefail
    export IDP_CLIENT_ID="$(< "$CREDENTIALS_DIRECTORY/idp-client-id")"
    exec ${pomerium}/bin/pomerium -config ${configFile}
  '';
  unitSettings = {
    Unit = {
      Description = "Pomerium portable service";
      Wants = [
        "network-online.target"
      ];
      After = [
        "network-online.target"
        "userborn.service"
        "sops-install-secrets.service"
        "pomerium-network.service"
      ];
      Requires = [
        "sops-install-secrets.service"
        "pomerium-network.service"
      ];
      PartOf = [
        "pomerium-network.service"
      ];
    };
    Service = hardening // {
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      User = "5003";
      Group = "5003";
      StateDirectory = "data/pomerium";
      StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/pomerium";
      LoadCredential = map (name: "${name}:${config.sops.secrets."pomerium-${name}".path}") credentials;
      ExecStart = start;
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
      # Port zero supports Go's probes; upstream also binds allocated ephemeral ports.
      SocketBindDeny = [
        "ipv4:tcp:1-65535"
        "ipv6:tcp:1-65535"
        "ipv4:udp:1-65535"
        "ipv6:udp:1-65535"
      ];
      SocketBindAllow = [
        "ipv4:tcp:8080"
        "ipv4:tcp:5443"
        "ipv4:tcp:28080"
        "ipv4:tcp:32768-60999"
        "ipv6:tcp:32768-60999"
      ];
    };
    Install.WantedBy = "system-manager.target";
  };
  unit = pkgs.writeText "pomerium.service" (
    lib.generators.toINI { listsAsDuplicateKeys = true; } unitSettings
  );
  image = pkgs.portableService {
    pname = "pomerium";
    version = pomerium.version;
    description = "Mashu Pomerium";
    units = [ unit ];
    symlinks = [
      {
        object = unit;
        symlink = "var/lib/data/pomerium/.image-unit";
      }
    ];
  };
in
{
  system-manager.preActivationAssertions.pomeriumPorts = {
    enable = true;
    # Internal listeners must fit the declared bind and egress range.
    script = ''
      read -r first last < /proc/sys/net/ipv4/ip_local_port_range
      test "$first" = 32768 && test "$last" = 60999
    '';
  };
  sops.secrets = builtins.listToAttrs (
    map (name: {
      name = "pomerium-${name}";
      value = {
        sopsFile = ../../secrets/mashu.sops.yaml;
        key = "pomerium_${builtins.replaceStrings [ "-" ] [ "_" ] name}";
        restartUnits = [ "pomerium.service" ];
      };
    }) credentials
  );
  environment.etc."nftables/pomerium.nft".source = ./firewall.nft;
  systemd.services.pomerium-network = import ../firewall.nix {
    inherit pkgs;
    name = "pomerium";
    policy = ./firewall.nft;
  };
  systemd.services.pomerium = import ../portable.nix {
    inherit image;
    name = "pomerium";
    settings = unitSettings;
  };
}
