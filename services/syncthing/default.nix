# Portable Syncthing and its existing uptime heartbeat; all mutable state is backed up.
# Syncthing owns its device/folder configuration in state; Nix owns execution/policy.
{ config, lib, pkgs, ... }:
let
  syncthing = pkgs.callPackage ../../pkgs/syncthing.nix {};
  hardening = import ../hardening.nix;
  environment = {
    HOME = "/var/lib/data/syncthing";
    SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    # Nix controls upgrades; never replace a store binary through Syncthing's updater.
    STNOUPGRADE = "1";
  };
  unit = pkgs.writeText "syncthing.service" (lib.generators.toINI { listsAsDuplicateKeys = true; } {
    Unit = {
      Description = "Syncthing portable service";
      Wants = "network-online.target";
      After = "network-online.target userborn.service syncthing-network.service";
      Requires = "syncthing-network.service";
      PartOf = "syncthing-network.service";
    };
    Service = hardening // {
      Environment = lib.mapAttrsToList (name: value: "${name}=${value}") environment;
      User = "5001"; Group = "5001";
      StateDirectory = "data/syncthing"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/syncthing";
      ExecStart = "${syncthing}/bin/syncthing serve --home=/var/lib/data/syncthing/config --gui-address=127.0.0.1:8384 --no-browser --no-restart --no-upgrade --no-port-probing";
      Restart = "on-failure"; RestartSec = 5;
      SuccessExitStatus = [ 3 4 ];
      RestartForceExitStatus = [ 3 4 ];
      MemoryMax = "2G"; TasksMax = 256;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      LockPersonality = true; SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" ];
      # Port zero supports Go's family probes/outbound UDP; named listeners stay fixed.
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:8384" "ipv4:tcp:22000" "ipv6:tcp:22000" "ipv4:udp:22000" "ipv6:udp:22000" "ipv4:udp:21027" "ipv6:udp:21027" ];
    };
    Install.WantedBy = "system-manager.target";
  });
  image = (pkgs.portableService {
    pname = "syncthing"; version = syncthing.version;
    description = "Mashu Syncthing";
    units = [ unit ];
    symlinks = [
      { object = unit; symlink = "var/lib/data/syncthing/.image-unit"; }
    ];
  }).overrideAttrs (old: {
    buildCommand = old.buildCommand + ''
      mv "$out/syncthing_${syncthing.version}.raw" "$out/syncthing.raw"
    '';
  });
in {
  system-manager.preActivationAssertions.syncthingIdentity = {
    enable = true;
    # Refuse activation if the reserved identity belongs to another account.
    script = ''
      for database in passwd group; do
        entry="$(/usr/bin/getent "$database" 5001 || true)"
        if [ -n "$entry" ] && [ "''${entry%%:*}" != syncthing ]; then
          echo "Syncthing UID/GID 5001 is already allocated" >&2; exit 1
        fi
        entry="$(/usr/bin/getent "$database" syncthing || true)"
        IFS=: read -r _ _ number _ <<< "$entry"
        if [ -n "$entry" ] && [ "$number" != 5001 ]; then
          echo "Existing Syncthing account has a different UID/GID" >&2; exit 1
        fi
      done
    '';
  };
  services.userborn.enable = lib.mkForce true;
  users.users = lib.mkForce {
    syncthing = { isSystemUser = true; uid = 5001; group = "syncthing"; shell = "/usr/sbin/nologin"; };
  };
  users.groups = lib.mkForce { syncthing.gid = 5001; };
  sops.secrets.syncthing-heartbeat-url = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "syncthing_heartbeat_url";
  };
  systemd.services.syncthing-network = {
    wantedBy = [ "system-manager.target" ];
    before = [ "syncthing.service" "syncthing-heartbeat.service" ];
    serviceConfig = hardening // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f ${./firewall.nft}";
      ExecStop = "${pkgs.nftables}/bin/nft destroy table inet syncthing_egress";
    };
  };
  build.scripts.syncthing = import ../activate-portable.nix {
    inherit pkgs image;
    name = "syncthing";
    healthURL = "http://127.0.0.1:8384/rest/noauth/health";
  };
  systemd.services.syncthing-heartbeat = {
    after = [ "syncthing.service" "sops-install-secrets.service" "syncthing-network.service" ];
    requires = [ "sops-install-secrets.service" "syncthing-network.service" ];
    unitConfig.ConditionPathExists = "/var/lib/data/syncthing/config/config.xml";
    environment.CURL_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    script = ''
      # Read the URL inside curl, keeping its secret token out of argv and logs.
      ${pkgs.curl}/bin/curl --fail --silent --show-error --max-time 10 --output /dev/null \
        --proto '=https' --variable "heartbeat@$CREDENTIALS_DIRECTORY/url" --expand-url '{{heartbeat:trim}}'
    '';
    serviceConfig = hardening // {
      Type = "oneshot"; User = "syncthing"; Group = "syncthing";
      # A maintenance pause skips the ping; the external monitor still sees downtime.
      ExecCondition = "${pkgs.curl}/bin/curl --fail --silent --show-error --max-time 10 --output /dev/null http://127.0.0.1:8384/rest/noauth/health";
      LoadCredential = [ "url:${config.sops.secrets.syncthing-heartbeat-url.path}" ];
      TimeoutStartSec = 30;
    };
  };
  systemd.timers.syncthing-heartbeat = {
    wantedBy = [ "system-manager.target" ];
    timerConfig = { OnActiveSec = "1min"; OnUnitActiveSec = "1min"; AccuracySec = "5s"; };
  };
}
