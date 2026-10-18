# Minimal ARM builder and synthetic service-test guest. Host QEMU/image tools run on x86.
# No host store, production identity, cloud-init, APT or automatic OS upgrades are exposed.
{ lib, pkgs, modulesPath, hostPkgs, ... }: {
  imports = [
    "${modulesPath}/profiles/minimal.nix"
    "${modulesPath}/virtualisation/qemu-vm.nix"
  ];
  system.stateVersion = "26.05";
  networking.hostName = "mashu-test";
  users.users.builder = {
    isNormalUser = true;
    uid = 1000;
    extraGroups = [ "wheel" ];
    initialHashedPassword = "!";
  };
  security.sudo.wheelNeedsPassword = false;
  services.openssh = {
    enable = true;
    # Only the public key is shared into the guest, on a read-only mount at boot.
    authorizedKeysFiles = lib.mkForce [ "/run/mashu-vm-authorized_keys" ];
    settings = { PasswordAuthentication = false; KbdInteractiveAuthentication = false; PermitRootLogin = "no"; };
  };
  # Copy the public key to a root-owned runtime file so SSH StrictModes is independent
  # of the workstation UID used by the read-only shared filesystem.
  systemd.services.mashu-vm-key = {
    requiredBy = [ "sshd.service" ];
    before = [ "sshd.service" ];
    unitConfig.RequiresMountsFor = "/run/mashu-key";
    script = "install -m 0644 /run/mashu-key/authorized_keys /run/mashu-vm-authorized_keys";
    serviceConfig = { Type = "oneshot"; RemainAfterExit = true; };
  };
  services.resolved.enable = true;
  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    trusted-users = [ "root" "builder" ];
  };
  # This guest executes supplied derivations; it does not need a channel or a
  # full Nixpkgs source tree embedded in its boot image.
  nix.channel.enable = false;
  nixpkgs.flake.setFlakeRegistry = false;
  nixpkgs.flake.setNixPath = false;
  nix.gc.automatic = false;
  nix.optimise.automatic = false;
  system.autoUpgrade.enable = false;
  environment.systemPackages = with pkgs; [ python3 curl iproute2 procps util-linux nettools ];
  # System Manager needs Ubuntu-style writable unit directories. Copy directory
  # structure once, preserving NixOS's unit symlinks and later fixture additions.
  system.activationScripts.mashuVmUnits = {
    deps = [ "etc" ];
    text = ''
      if test -L /etc/systemd/system; then
        mashu_unit_source=$(readlink -f /etc/systemd/system)
        unlink /etc/systemd/system
        mkdir -p /etc/systemd/system
        cp -a "$mashu_unit_source/." /etc/systemd/system/
        find /etc/systemd/system -type d -exec chmod u+w {} +
        # System Manager supplies its own instance of this switch-only target.
        rm -f /etc/systemd/system/sysinit-reactivation.target
      fi
    '';
  };
  # Our Ubuntu service definitions use these fixed paths. These compatibility links
  # exercise their commands on NixOS without pretending to reproduce Ubuntu's OS setup.
  systemd.tmpfiles.rules = [
    "L+ /usr/bin/systemctl - - - - ${pkgs.systemd}/bin/systemctl"
    "L+ /usr/bin/python3 - - - - ${pkgs.python3}/bin/python3"
    "L+ /usr/bin/hostname - - - - ${pkgs.nettools}/bin/hostname"
    "L+ /usr/sbin/nologin - - - - ${pkgs.util-linux}/bin/nologin"
  ];
  virtualisation = {
    host.pkgs = hostPkgs;
    graphics = false;
    memorySize = 4096;
    cores = 4;
    diskSize = 24576;
    writableStore = true;
    writableStoreUseTmpfs = false;
    mountHostNixStore = false;
    useNixStoreImage = true;
    # mkForce replaces the VM module's default host-directory shares entirely.
    sharedDirectories = lib.mkForce {
      keys = { source = ''"$VM_KEY_DIRECTORY"''; target = "/run/mashu-key"; writable = false; };
    };
    # NixOS's ARM runner already selects the max CPU and KVM-to-TCG fallback.
    qemu.networkingOptions = lib.mkForce [
      ''-netdev user,id=user.0,hostfwd=tcp:127.0.0.1:$VM_SSH_PORT-:22''
      "-device virtio-net-pci,netdev=user.0,mac=52:54:00:12:34:56"
    ];
  };
}
