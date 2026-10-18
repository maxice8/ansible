# Native Backrest: one /var/lib/data source, private credentials and read-only application access.
# The encrypted seed initializes fresh installs; subsequent UI settings remain in its state directory.
{ config, lib, pkgs, ... }:
let
  backrest = pkgs.callPackage ../../pkgs/backrest.nix {};
  fields = { config = "backrest_config_json"; id_ed25519 = "backrest_ssh_key";
    known_hosts = "backrest_known_hosts"; repository-password = "backrest_repository_password"; };
  readOnlyBackup = import ../hardening.nix // {
    User = "backrest"; Group = "backrest";
    CapabilityBoundingSet = "CAP_DAC_READ_SEARCH";
    AmbientCapabilities = "CAP_DAC_READ_SEARCH";
    ReadOnlyPaths = [ "/var/lib/data" ];
    InaccessiblePaths = [ "/var/lib/sops-nix" "/run/secrets" "/etc/ssh" ];
    # Deny handle-based reads that could bypass the deliberately hidden paths.
    SystemCallFilter = "~open_by_handle_at name_to_handle_at";
  };
in {
  sops.secrets = lib.mapAttrs' (name: key: lib.nameValuePair "backrest-${name}" {
    sopsFile = ../../secrets/mashu.sops.yaml; inherit key; restartUnits = [ "backrest.service" ];
  }) fields;
  systemd.services.backrest-network = import ../firewall.nix { inherit pkgs; name = "backrest"; uid = 5008; publicTCP = [ 23 443 ]; };
  systemd.services.backrest = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "backrest-network.service" ];
    requires = [ "sops-install-secrets.service" "backrest-network.service" ]; partOf = [ "backrest-network.service" ];
    path = [ pkgs.openssh pkgs.systemd pkgs.coreutils ];
    environment = {
      BACKREST_CONFIG = "/var/lib/data/backrest/config.json";
      BACKREST_DATA = "/var/lib/data/backrest"; BACKREST_PORT = "127.0.0.1:9898";
      RESTIC_PASSWORD_FILE = "/run/credentials/backrest.service/repository-password";
      XDG_CACHE_HOME = "/var/cache/backrest"; HOME = "/var/lib/data/backrest";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"; TZ = "America/Sao_Paulo";
    };
    preStart = ''
      if [ ! -s "$BACKREST_CONFIG" ]; then
        cp "$CREDENTIALS_DIRECTORY/config" "$BACKREST_CONFIG"
        chmod 600 "$BACKREST_CONFIG"
      fi
    '';
    serviceConfig = readOnlyBackup // {
      StateDirectory = "data/backrest"; StateDirectoryMode = "0700";
      CacheDirectory = "backrest"; WorkingDirectory = "/var/lib/data/backrest";
      LoadCredential = lib.mapAttrsToList (name: _: "${name}:${config.sops.secrets."backrest-${name}".path}") fields;
      ExecStart = "${backrest}/bin/backrest";
      Restart = "on-failure"; RestartSec = 5; MemoryMax = "512M"; TasksMax = 256;
      RestrictNamespaces = true; RestrictRealtime = true; ProtectKernelLogs = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:9898" ];
    };
  };
  # The backup identity may start exactly this immutable capture unit, not arbitrary host units.
  environment.etc."polkit-1/rules.d/50-backrest-capture.rules".text = ''
    polkit.addRule(function(action, subject) {
      if (subject.user == "backrest" && action.id == "org.freedesktop.systemd1.manage-units" &&
          action.lookup("unit") == "homelab-backup-capture.service" && action.lookup("verb") == "start") {
        return polkit.Result.YES;
      }
    });
  '';
  systemd.services.homelab-backup-capture = {
    # A changed on-demand unit must not be started by System Manager activation.
    restartIfChanged = false;
    # Prefix + grants only these fixed systemctl calls the privilege to pause/resume writers.
    # ExecStopPost also resumes them if capture fails; data copying remains unprivileged.
    serviceConfig = readOnlyBackup // {
      Type = "oneshot"; StateDirectory = "data/backup-capture"; StateDirectoryMode = "0700";
      ExecStartPre = "+${pkgs.systemd}/bin/systemctl stop pomerium.service syncthing.service";
      ExecStart = "${pkgs.python3}/bin/python3 ${./backup-capture.py}";
      ExecStopPost = "+${pkgs.systemd}/bin/systemctl start pomerium.service syncthing.service";
      TimeoutStartSec = "5min";
    };
  };
}
