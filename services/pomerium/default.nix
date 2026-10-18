# Portable Pomerium with private credentials/state and a separate privileged egress unit.
# The embedded Envoy needs executable private /tmp and loopback ephemeral RPC ports.
{ config, lib, pkgs, ... }:
let
  pomerium = pkgs.callPackage ../../pkgs/pomerium.nix {};
  credentials = [ "cookie-secret" "shared-secret" "idp-client-id" "idp-client-secret" ];
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
  unit = pkgs.writeText "pomerium.service" (lib.generators.toINI { listsAsDuplicateKeys = true; } {
    Unit = {
      Description = "Pomerium portable service";
      Wants = "network-online.target";
      After = "network-online.target userborn.service sops-install-secrets.service pomerium-network.service";
      Requires = "sops-install-secrets.service pomerium-network.service";
      PartOf = "pomerium-network.service";
    };
    Service = hardening // {
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      User = "5003"; Group = "5003";
      StateDirectory = "data/pomerium"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/pomerium";
      LoadCredential = map (name: "${name}:${config.sops.secrets."pomerium-${name}".path}") credentials;
      ExecStart = start;
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
    Install.WantedBy = "system-manager.target";
  });
  image = (pkgs.portableService {
    pname = "pomerium"; version = pomerium.version;
    description = "Mashu Pomerium";
    units = [ unit ];
    symlinks = [
      # Embedded Envoy keeps the upstream ELF interpreter path when extracted.
      { object = "${pkgs.glibc}/lib"; symlink = "lib"; }
      { object = "${pkgs.glibc}/lib"; symlink = "lib64"; }
      { object = unit; symlink = "var/lib/data/pomerium/.image-unit"; }
    ];
  }).overrideAttrs (old: {
    buildCommand = old.buildCommand + ''
      mv "$out/pomerium_${pomerium.version}.raw" "$out/pomerium.raw"
    '';
  });
in {
  system-manager.preActivationAssertions.pomeriumIdentity = {
    enable = true;
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 5003 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != pomerium ]; then
          echo "Pomerium UID/GID 5003 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" pomerium || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 5003 ]; then
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
    pomerium = { isSystemUser = true; uid = 5003; group = "pomerium"; shell = "/usr/sbin/nologin"; };
  };
  users.groups = lib.mkForce { pomerium.gid = 5003; };
  # map creates one SOPS secret per credential; replaceStrings maps filenames to keys.
  sops.secrets = builtins.listToAttrs (map (name: {
    name = "pomerium-${name}";
    value = {
      sopsFile = ../../secrets/mashu.sops.yaml;
      key = "pomerium_${builtins.replaceStrings [ "-" ] [ "_" ] name}";
      restartUnits = [ "pomerium.service" ];
    };
  }) credentials);
  systemd.services.pomerium-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "pomerium.service" ];
    serviceConfig = hardening // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./firewall.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet pomerium_egress";
    };
  };
  build.scripts.pomerium = import ../activate-portable.nix {
    inherit pkgs image;
    name = "pomerium";
    healthURL = "http://127.0.0.1:28080/readyz";
  };
}
