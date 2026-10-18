# Portable ASF/.NET with mutable bot state separated from immutable application/UI files.
# Steam uses dynamic public endpoints; private networks and host services stay denied.
{ lib, pkgs, ... }:
let
  asf = pkgs.callPackage ../../pkgs/archisteamfarm.nix {};
  hardening = import ../hardening.nix;
  environment = {
    HOME = "/var/lib/data/archisteamfarm";
    ASPNETCORE_URLS = "http://127.0.0.1:1242";
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    DOTNET_CLI_TELEMETRY_OPTOUT = "1";
    DOTNET_EnableDiagnostics = "0";
  };
  unit = pkgs.writeText "archisteamfarm.service" (lib.generators.toINI { listsAsDuplicateKeys = true; } {
    Unit = {
      Description = "ArchiSteamFarm portable service";
      Wants = "network-online.target";
      After = "network-online.target userborn.service archisteamfarm-network.service";
      Requires = "archisteamfarm-network.service";
      PartOf = "archisteamfarm-network.service";
    };
    Service = hardening // {
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      User = "5013"; Group = "5013";
      StateDirectory = "data/archisteamfarm"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/archisteamfarm";
      ExecStartPre = "${pkgs.coreutils}/bin/ln -sfn /etc/archisteamfarm/www /var/lib/data/archisteamfarm/www";
      ExecStart = "${asf}/bin/ArchiSteamFarm --path=/var/lib/data/archisteamfarm --no-restart";
      Restart = "always"; RestartSec = 5;
      MemoryMax = "512M"; TasksMax = 256;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      LockPersonality = true; SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:1242" ];
    };
    Install.WantedBy = "system-manager.target";
  });
  image = (pkgs.portableService {
    pname = "archisteamfarm"; version = asf.version;
    description = "Mashu ArchiSteamFarm";
    units = [ unit ];
    symlinks = [
      { object = "${asf}/lib/ASF/www"; symlink = "etc/archisteamfarm/www"; }
      { object = unit; symlink = "var/lib/data/archisteamfarm/.image-unit"; }
    ];
  }).overrideAttrs (old: {
    buildCommand = old.buildCommand + ''
      mv "$out/archisteamfarm_${asf.version}.raw" "$out/archisteamfarm.raw"
    '';
  });
in {
  systemd.services.archisteamfarm-network = import ../firewall.nix {
    inherit pkgs; name = "archisteamfarm"; uid = 5013;
    publicTCP = null; publicUDP = null;
  };
  build.scripts.archisteamfarm = import ../activate-portable.nix {
    inherit pkgs image;
    name = "archisteamfarm";
    healthURL = "http://127.0.0.1:1242/";
  };
}
