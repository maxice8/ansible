# Native ASF/.NET with mutable bot state separated from immutable application/UI files.
# Steam uses dynamic public endpoints; private networks and host services stay denied.
{ pkgs, ... }:
let asf = pkgs.callPackage ../pkgs/archisteamfarm.nix {};
in {
  environment.etc."archisteamfarm/www".source = "${asf}/lib/ASF/www";
  systemd.services.archisteamfarm-network = import ./egress.nix {
    inherit pkgs; name = "archisteamfarm"; uid = 976;
    publicTCP = null; publicUDP = null;
  };
  systemd.services.archisteamfarm = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "archisteamfarm-network.service" ];
    requires = [ "archisteamfarm-network.service" ];
    partOf = [ "archisteamfarm-network.service" ];
    environment = {
      HOME = "/var/lib/data/archisteamfarm";
      ASPNETCORE_URLS = "http://127.0.0.1:1242";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      DOTNET_CLI_TELEMETRY_OPTOUT = "1";
      DOTNET_EnableDiagnostics = "0";
    };
    preStart = ''
      # A stable link makes the official UI available with ASF's custom state directory.
      ln -sfn /etc/archisteamfarm/www /var/lib/data/archisteamfarm/www
    '';
    serviceConfig = import ./hardening.nix // {
      User = "archisteamfarm"; Group = "archisteamfarm";
      StateDirectory = "data/archisteamfarm"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/archisteamfarm";
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
  };
}
