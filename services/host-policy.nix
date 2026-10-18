# Ubuntu owns its kernel, networking, SSH/updates binaries and base units.
# Nix owns their small host policies; application isolation remains in service modules.
{ config, pkgs, ... }:
let
  files = {
    "ssh/sshd_config.d/10-homelab.conf" = ''
      AuthenticationMethods publickey
      PasswordAuthentication no
      KbdInteractiveAuthentication no
      PermitEmptyPasswords no
      PermitRootLogin no
      AllowUsers ubuntu
      X11Forwarding no
      AllowAgentForwarding no
      AllowTcpForwarding local
      PermitTunnel no
      MaxAuthTries 3
      LoginGraceTime 30
    '';
    "systemd/journald.conf.d/10-retention.conf" = ''
      [Journal]
      Storage=persistent
      Compress=yes
      SystemMaxUse=512M
      SystemKeepFree=5G
      SystemMaxFileSize=64M
      MaxRetentionSec=7day
      MaxFileSec=1day
    '';
    "systemd/coredump.conf.d/10-retention.conf" = ''
      [Coredump]
      Storage=external
      Compress=yes
      ProcessSizeMax=1G
      ExternalSizeMax=1G
      MaxUse=1G
      KeepFree=5G
    '';
    "apt/apt.conf.d/20auto-upgrades" = ''
      APT::Periodic::Enable "1";
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Unattended-Upgrade "1";
      APT::Periodic::AutocleanInterval "7";
    '';
    "apt/apt.conf.d/52unattended-upgrades-local" = ''
      Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
      Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
      Unattended-Upgrade::Remove-Unused-Dependencies "true";
      Unattended-Upgrade::Automatic-Reboot "false";
    '';
    "sysctl.d/90-homelab.conf" = ''
      fs.inotify.max_user_instances = 8192
      fs.inotify.max_user_watches = 524288
      net.ipv6.conf.all.accept_ra = 2
      net.ipv6.conf.default.accept_ra = 2
    '';
  };
in {
  environment.etc = builtins.mapAttrs (_: text: { inherit text; }) files // {
    "netplan/60-public-ipv6.yaml" = {
      mode = "0600";
      text = ''
        network:
          version: 2
          ethernets:
            enp0s6:
              accept-ra: true
              dhcp6: true
      '';
    };
    "nftables.conf".source = ./host-firewall.nft;
  };
  systemd.services.homelab-firewall = {
    description = "Native host ingress and forwarding policy";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-pre.target" ];
    before = [ "network-pre.target" "tailscaled.service" ];
    # Load before interfaces are configured, including on a cold boot.
    unitConfig.DefaultDependencies = false;
    restartTriggers = [ config.environment.etc."nftables.conf".source ];
    serviceConfig = import ./hardening.nix // {
      Type = "oneshot"; RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f /etc/nftables.conf";
      ExecReload = "${pkgs.nftables}/bin/nft -f /etc/nftables.conf";
      # No flush on stop: keep protection while changing generations.
    };
  };
  systemd.services.homelab-host-policy = {
    description = "Apply Ubuntu SSH, journal and sysctl policy";
    wantedBy = [ "system-manager.target" ];
    wants = [ "ssh.service" "apt-daily.timer" "apt-daily-upgrade.timer" "fstrim.timer" ];
    after = [ "ssh.service" ];
    restartTriggers = map (name: config.environment.etc.${name}.source) (builtins.attrNames files);
    # These fixed host operations intentionally run outside application sandboxes.
    script = ''
      /usr/sbin/sshd -t
      /usr/lib/systemd/systemd-sysctl /etc/sysctl.d/90-homelab.conf
      /usr/bin/systemctl reload ssh.service
      /usr/bin/systemctl restart systemd-journald.service
    '';
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; NoNewPrivileges = true; };
  };
}
