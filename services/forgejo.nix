# Native Forgejo with its original encrypted configuration and private repository state.
# Forgejo initializes shared Git hooks during web startup.
{ config, pkgs, ... }:
let
  forgejo = pkgs.callPackage ../pkgs/forgejo.nix {};
  command = "${forgejo}/bin/forgejo --work-path /var/lib/data/forgejo --custom-path /var/lib/data/forgejo/gitea --config %d/app.ini";
in {
  sops.secrets.forgejo-config = {
    sopsFile = ../secrets/mashu.sops.yaml; key = "forgejo_app_ini";
    restartUnits = [ "forgejo.service" ];
  };
  systemd.services.forgejo-network = import ./egress.nix {
    inherit pkgs; name = "forgejo"; uid = 62005;
    localTCP = [ 3000 2222 ]; publicTCP = [ 22 25 443 465 587 9418 ];
  };
  systemd.services.forgejo = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "forgejo-network.service" ];
    requires = [ "sops-install-secrets.service" "forgejo-network.service" ];
    partOf = [ "forgejo-network.service" ];
    path = [ pkgs.bash pkgs.git pkgs.git-lfs pkgs.openssh pkgs.gnupg pkgs.gzip pkgs.coreutils ];
    environment = {
      HOME = "/var/lib/data/forgejo/gitea/git";
      GITEA_WORK_DIR = "/var/lib/data/forgejo";
      GITEA_CUSTOM = "/var/lib/data/forgejo/gitea";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    };
    serviceConfig = import ./hardening.nix // {
      User = "forgejo"; Group = "forgejo";
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
  };
}
