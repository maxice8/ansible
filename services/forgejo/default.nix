# Portable Forgejo with its original encrypted configuration and private repository state.
# Forgejo initializes shared Git hooks during web startup.
{ config, lib, pkgs, ... }:
let
  forgejo = pkgs.callPackage ../../pkgs/forgejo.nix {};
  command = "${forgejo}/bin/forgejo --work-path /var/lib/data/forgejo --custom-path /var/lib/data/forgejo/gitea --config %d/app.ini";
  hardening = import ../hardening.nix;
  environment = {
    PATH = lib.makeBinPath [ pkgs.bash pkgs.git pkgs.git-lfs pkgs.openssh pkgs.gnupg pkgs.gzip pkgs.coreutils ];
    HOME = "/var/lib/data/forgejo/gitea/git";
    GITEA_WORK_DIR = "/var/lib/data/forgejo";
    GITEA_CUSTOM = "/var/lib/data/forgejo/gitea";
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
  };
  # Git hooks use /usr/bin/env bash; Git and SSH also need a shell and passwd lookup.
  passwd = pkgs.writeText "forgejo-passwd" "forgejo:x:5005:5005:Forgejo:/var/lib/data/forgejo/gitea/git:/bin/sh\n";
  group = pkgs.writeText "forgejo-group" "forgejo:x:5005:\n";
  unit = pkgs.writeText "forgejo.service" (lib.generators.toINI { listsAsDuplicateKeys = true; } {
    Unit = {
      Description = "Forgejo portable service";
      Wants = "network-online.target";
      After = "network-online.target userborn.service sops-install-secrets.service forgejo-network.service";
      Requires = "sops-install-secrets.service forgejo-network.service";
      PartOf = "forgejo-network.service";
    };
    Service = hardening // {
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      User = "5005"; Group = "5005";
      StateDirectory = "data/forgejo"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/forgejo";
      LoadCredential = [ "app.ini:${config.sops.secrets.forgejo-config.path}" ];
      ExecStartPre = [ "${command} migrate" ];
      ExecStart = "${command} web";
      Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "1G"; TasksMax = 256;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      LockPersonality = true; SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:3000" "ipv4:tcp:2222" "ipv6:tcp:2222" ];
    };
    Install.WantedBy = "system-manager.target";
  });
  image = (pkgs.portableService {
    pname = "forgejo"; version = forgejo.version;
    description = "Mashu Forgejo";
    units = [ unit ];
    symlinks = [
      { object = "${pkgs.bash}/bin/sh"; symlink = "bin/sh"; }
      { object = "${pkgs.coreutils}/bin/env"; symlink = "usr/bin/env"; }
      { object = passwd; symlink = "etc/passwd"; }
      { object = group; symlink = "etc/group"; }
      { object = unit; symlink = "var/lib/data/forgejo/.image-unit"; }
    ];
  }).overrideAttrs (old: {
    buildCommand = old.buildCommand + ''
      mv "$out/forgejo_${forgejo.version}.raw" "$out/forgejo.raw"
    '';
  });
in {
  sops.secrets.forgejo-config = {
    sopsFile = ../../secrets/mashu.sops.yaml; key = "forgejo_app_ini";
    restartUnits = [ "forgejo.service" ];
  };
  systemd.services.forgejo-network = import ../firewall.nix {
    inherit pkgs; name = "forgejo"; uid = 5005;
    localTCP = [ 3000 2222 ]; publicTCP = [ 22 25 443 465 587 9418 ];
  };
  build.scripts.forgejo = import ../activate-portable.nix {
    inherit pkgs image;
    name = "forgejo";
    healthURL = "http://127.0.0.1:3000/api/healthz";
  };
}
