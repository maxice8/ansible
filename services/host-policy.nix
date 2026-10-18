# Configure Ubuntu host policies with Nix.
# Ubuntu supplies the kernel, networking, SSH, OS updates and base units.
{ config, pkgs, ... }:
let
  files = {
    # Limit Ubuntu's automatic ordinary-account IDs to avoid the reserved service range.
    "adduser.conf" = ''
      # Keep automatic ordinary accounts outside the service UID/GID range 5000-5999.
      FIRST_UID=1000
      LAST_UID=4999
      FIRST_GID=1000
      LAST_GID=4999
      FIRST_SYSTEM_UID=100
      LAST_SYSTEM_UID=999
      FIRST_SYSTEM_GID=100
      LAST_SYSTEM_GID=999
    '';
    # Harden OpenSSH: allow only ubuntu with public keys and restrict forwarding.
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
    # Persist compressed system logs for up to seven days, capped at 512 MiB.
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
    # Bound crash-dump processing and storage while keeping 5 GiB of disk space free.
    "systemd/coredump.conf.d/10-retention.conf" = ''
      [Coredump]
      Storage=external
      Compress=yes
      ProcessSizeMax=1G
      ExternalSizeMax=1G
      MaxUse=1G
      KeepFree=5G
    '';
    # Refresh package lists and install unattended upgrades daily; clean downloads weekly.
    "apt/apt.conf.d/20auto-upgrades" = ''
      APT::Periodic::Enable "1";
      APT::Periodic::Update-Package-Lists "1";
      APT::Periodic::Unattended-Upgrade "1";
      APT::Periodic::AutocleanInterval "7";
    '';
    # Remove unused kernels and dependencies after upgrades without automatic reboots.
    "apt/apt.conf.d/52unattended-upgrades-local" = ''
      Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
      Unattended-Upgrade::Remove-New-Unused-Dependencies "true";
      Unattended-Upgrade::Remove-Unused-Dependencies "true";
      Unattended-Upgrade::Automatic-Reboot "false";
    '';
    # Raise file-watcher limits and accept IPv6 router advertisements even with forwarding enabled.
    "sysctl.d/90-homelab.conf" = ''
      fs.inotify.max_user_instances = 8192
      fs.inotify.max_user_watches = 524288
      net.ipv6.conf.all.accept_ra = 2
      net.ipv6.conf.default.accept_ra = 2
    '';
  };
in
{
  environment.etc = builtins.mapAttrs (_: text: { inherit text; }) files // {
    "adduser.conf" = {
      text = files."adduser.conf";
      # This package-provided file exists on a fresh Ubuntu installation.
      replaceExisting = true;
    };
    # Enable router advertisements and DHCPv6 on Mashu's public network interface.
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
    # Manage login defaults without changing files during activation.
    "login.defs" = {
      source = ./login.defs;
      replaceExisting = true;
    };
    # Load the shared host ingress and forwarding rules from their dedicated policy file.
    "nftables.conf".source = ./host-firewall.nft;
  };
  systemd.services.homelab-firewall = {
    description = "Native host ingress and forwarding policy";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-pre.target" ];
    before = [
      "network-pre.target"
      "tailscaled.service"
    ];
    # Load before interfaces are configured, including on a cold boot.
    unitConfig.DefaultDependencies = false;
    restartTriggers = [ config.environment.etc."nftables.conf".source ];
    serviceConfig = import ./hardening.nix // {
      Type = "oneshot";
      RemainAfterExit = true;
      CapabilityBoundingSet = "CAP_NET_ADMIN";
      ExecStart = "${pkgs.nftables}/bin/nft -f /etc/nftables.conf";
      ExecReload = "${pkgs.nftables}/bin/nft -f /etc/nftables.conf";
      # No flush on stop: keep protection while changing generations.
    };
  };
  systemd.services.homelab-host-policy = {
    description = "Apply Ubuntu SSH, journal and sysctl policy";
    wantedBy = [ "system-manager.target" ];
    wants = [
      "ssh.service"
      "apt-daily.timer"
      "apt-daily-upgrade.timer"
      "fstrim.timer"
    ];
    after = [ "ssh.service" ];
    restartTriggers = map (name: config.environment.etc.${name}.source) (
      builtins.attrNames files ++ [ "login.defs" ]
    );
    # These fixed host operations intentionally run outside application sandboxes.
    script = ''
      /usr/sbin/sshd -t
      /usr/lib/systemd/systemd-sysctl /etc/sysctl.d/90-homelab.conf
      /usr/bin/systemctl reload ssh.service
      /usr/bin/systemctl restart systemd-journald.service
    '';
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      NoNewPrivileges = true;
    };
  };
}
