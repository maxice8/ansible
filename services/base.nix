# Configure System Manager, secrets and the service data directory.
# Modules receive flake inputs through specialArgs.
{ inputs, ... }: {

  # Keep Ubuntu's Nix daemon, SSH and privilege tools.
  nix.enable = false;
  services.userborn.enable = false;
  security.sudo.enable = false;
  security.enableWrappers = false;
  services.openssh.enable = false;
  # Expose the managed profile at /run/current-system.
  system-manager.linkCurrentSystem = true;

  # Refuse activation on hosts lacking the systemd/cgroup baseline used by our units.
  system-manager.preActivationAssertions.hostBaseline = {
    enable = true;
    # Nix's two-single-quote syntax is a multiline string, here containing Bash.
    # Chain checks with &&: the activation runner does not enable shell errexit.
    script = ''
      read -r _ version _ < <(/usr/bin/systemctl --version) &&
      test "$version" -ge 259 &&
      test -f /sys/fs/cgroup/cgroup.controllers
    '';
  };

  # Create the parent at activation/boot: services can traverse it, not list it.
  systemd.tmpfiles.rules = [ "d /var/lib/data 0711 root root -" ];
  # A quoted attribute keeps the slash in one filename; toJSON serializes metadata.
  environment.etc."homelab/base.json".text = builtins.toJSON {
    dataRoot = "/var/lib/data";
  };
}
