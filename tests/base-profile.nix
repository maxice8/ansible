# Disposable VM fixture layered over the real host module, never deployed to Mashu.
# Parameters exercise updates, removal, rejected activation and failed service startup.
{ source, secretFile, version ? "one", removed ? false, fail ? false, brokenStart ? false, baseOnly ? false }:
let
  # Resolve the allowlisted source snapshot's locked inputs, not the whole checkout.
  inputs = (builtins.getFlake "path:${source}").inputs;
in inputs.system-manager.lib.makeSystemConfig {
  specialArgs = { inherit inputs; };
  modules = [
    # Exercise the shared base without enabling production apps or real credentials.
    ../services/base.nix
    { nixpkgs.hostPlatform = "aarch64-linux"; }
    ({ config, lib, pkgs, ... }: lib.mkIf (!baseOnly) {
      # mkForce overrides lower-priority module definitions. Replace the whole account
      # sets so userborn manages only fixtures, never Ubuntu's built-in defaults.
      services.userborn.enable = lib.mkForce true;
      users.users = lib.mkForce {
        homelab-probe = {
          isSystemUser = true;
          uid = 62000;
          group = "homelab-probe";
          shell = "/usr/sbin/nologin";
        };
        homelab-other = {
          isSystemUser = true;
          uid = 62001;
          group = "homelab-other";
          shell = "/usr/sbin/nologin";
        };
      };
      users.groups = lib.mkForce {
        homelab-probe.gid = 62000;
        homelab-other.gid = 62001;
      };

      # mkIf conditionally contributes module definitions; false omits this assertion.
      system-manager.preActivationAssertions.fixture = lib.mkIf fail {
        enable = true;
        script = "exit 1";
      };

      sops.secrets.probe = lib.mkIf (!removed) {
        # Copy only the encrypted synthetic file into the store under a stable name.
        sopsFile = builtins.path { path = builtins.toPath secretFile; name = "probe.sops.yaml"; };
        restartUnits = [ "homelab-probe.service" ];
      };

      systemd.services.homelab-peer-policy = lib.mkIf (!removed) {
        wantedBy = [ "system-manager.target" ];
        before = [ "homelab-probe.service" ];
        # // merges attribute sets; right-hand settings override shared defaults.
        serviceConfig = import ../services/hardening.nix // {
          Type = "oneshot";
          RemainAfterExit = true;
          CapabilityBoundingSet = "CAP_NET_ADMIN";
          # Interpolating packages/files embeds store paths and retains dependencies.
          ExecStart = "${pkgs.nftables}/bin/nft -f ${./peer-policy.nft}";
          ExecStop = "${pkgs.nftables}/bin/nft destroy table inet homelab_probe_test";
        };
      };

      systemd.services.homelab-probe = lib.mkIf (!removed) {
        wantedBy = [ "system-manager.target" ];
        after = [ "sops-install-secrets.service" "userborn.service" "homelab-peer-policy.service" ];
        # Account creation is ordering, not a dependency on userborn's lifetime.
        requires = [ "sops-install-secrets.service" "homelab-peer-policy.service" ];
        environment.PROBE_VERSION = version;
        serviceConfig = import ../services/hardening.nix // {
          User = "homelab-probe";
          Group = "homelab-probe";
          StateDirectory = "data/homelab-probe";
          StateDirectoryMode = "0700";
          # config reads the resolved module option; only the runtime secret path enters Nix.
          LoadCredential = [ "probe:${config.sops.secrets.probe.path}" ];
          ExecStart = if brokenStart then "${pkgs.coreutils}/bin/false"
            else "${pkgs.python3}/bin/python3 ${./probe.py}";
          Restart = if brokenStart then "no" else "on-failure";
          MemoryMax = "128M";
          TasksMax = 64;
          # BPF limits peer addresses, not ports; peer-policy.nft restricts loopback ports.
          IPAddressDeny = "any";
          IPAddressAllow = "localhost";
          # Restrict listening binds separately from outgoing connection destinations.
          SocketBindDeny = "any";
          SocketBindAllow = [ "ipv4:tcp:18080" ];
        };
      };
    })
  ];
}
