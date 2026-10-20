# Configure Ubuntu's Nix daemon and remove unused deployment builds.
{ config, pkgs, ... }:
{
  environment.systemPackages = [
    pkgs.bind.dnsutils
    pkgs.jq
    pkgs.btop
    pkgs.tcpdump
  ];

  # Bootstrap adds this include to Ubuntu's nix.conf. Keep Ubuntu's daemon.
  environment.etc."nix/homelab.conf" = {
    replaceExisting = true;
    text = ''
      extra-experimental-features = nix-command flakes
      extra-trusted-users = ubuntu
      max-jobs = 1
      cores = 1
    '';
  };
  systemd.services.homelab-nix-settings = {
    wantedBy = [ "system-manager.target" ];
    restartTriggers = [ config.environment.etc."nix/homelab.conf".source ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "/usr/bin/systemctl restart nix-daemon.service";
    };
  };

  systemd.services.homelab-nix-gc = {
    description = "Remove old deployment generations and unused Nix store paths";
    # Keep System Manager's registered profile while pruning old generations.
    unitConfig.ConditionPathExists = [
      "/nix/var/nix/gcroots/system-manager-current"
    ];
    script = ''
      test -e /nix/var/nix/gcroots/system-manager-current
      /usr/bin/nix-env --profile /nix/var/nix/profiles/system-manager-profiles/system-manager --delete-generations 1d
      /usr/bin/nix-store --gc
    '';
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
  };
  systemd.timers.homelab-nix-gc = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "15m";
    };
  };
  systemd.services.homelab-nix-optimise = {
    description = "Share identical files in the Nix store";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "/usr/bin/nix-store --optimise";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
  };
  systemd.timers.homelab-nix-optimise = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "weekly";
      Persistent = true;
      RandomizedDelaySec = "1h";
    };
  };
}
