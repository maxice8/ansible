# Minimal Ubuntu support shared by the isolated Pingvin container and CI engine.
# Keep Ubuntu's user-namespace restriction enabled; authorize only the Podman binary.
{ config, lib, pkgs, ... }:
let
  # The pinned System Manager adapter omits sub-ID fields. Ubuntu's native helper
  # applies our declared ranges without replacing other users' /etc/subuid/subgid entries.
  mappings = pkgs.writeShellScript "rootless-id-mappings" (lib.concatMapStringsSep "\n" (name:
    let
      user = config.users.users.${name};
      uid = builtins.head user.subUidRanges;
      gid = builtins.head user.subGidRanges;
    in ''
      if ! /usr/bin/grep -qxF '${name}:${toString uid.startUid}:${toString uid.count}' /etc/subuid; then
        /usr/sbin/usermod --add-subuids ${toString uid.startUid}-${toString (uid.startUid + uid.count - 1)} ${name}
      fi
      if ! /usr/bin/grep -qxF '${name}:${toString gid.startGid}:${toString gid.count}' /etc/subgid; then
        /usr/sbin/usermod --add-subgids ${toString gid.startGid}-${toString (gid.startGid + gid.count - 1)} ${name}
      fi
    '') [ "runner-engine" "pingvin-share" ]);
in {
  environment.etc."apparmor.d/homelab-podman".text = ''
    abi <abi/4.0>,
    include <tunables/global>
    profile homelab-podman /nix/store/*-podman-*/bin/{podman,.podman-wrapped} flags=(unconfined) {
      userns,
    }
  '';
  system-manager.preActivationAssertions.uidMappingHelpers = {
    enable = true;
    script = ''
      test -u /usr/bin/newuidmap && test -u /usr/bin/newgidmap &&
      test -x /usr/sbin/apparmor_parser
    '';
  };
  systemd.services.rootless-containers = {
    wantedBy = [ "system-manager.target" ];
    before = [ "runner-engine.service" "pingvin-share.service" ];
    after = [ "userborn.service" ];
    # Ordering suffices: restarting the account manager must not stop live containers.
    wants = [ "userborn.service" ];
    restartTriggers = [ config.environment.etc."apparmor.d/homelab-podman".source config.environment.etc."containers/containers.conf".source mappings ];
    serviceConfig = {
      Type = "oneshot"; RemainAfterExit = true;
      ExecStartPre = mappings;
      ExecStart = "/usr/sbin/apparmor_parser -r /etc/apparmor.d/homelab-podman";
      ExecStop = "/usr/sbin/apparmor_parser -R /etc/apparmor.d/homelab-podman";
      NoNewPrivileges = true; PrivateTmp = true; ProtectHome = true;
      CapabilityBoundingSet = [ "CAP_MAC_ADMIN" "CAP_AUDIT_WRITE" ];
    };
  };
  # Rootless helpers use uidmap from Ubuntu; all other runtime tools come from Nix.
  environment.etc."containers/policy.json".text = builtins.toJSON {
    default = [{ type = "insecureAcceptAnything"; }];
  };
  environment.etc."containers/registries.conf".text = ''
    unqualified-search-registries = ["docker.io"]
  '';
  environment.etc."containers/containers.conf".text = ''
    [containers]
    cgroups = "disabled"
    # Podman otherwise copies Oracle/overlay DNS addresses that our egress policy denies.
    dns_servers = ["1.1.1.1", "1.0.0.1"]
    [network]
    default_rootless_network_cmd = "slirp4netns"
    [engine]
    cgroup_manager = "cgroupfs"
    events_logger = "file"
    runtime = "crun"
    helper_binaries_dir = ["${pkgs.podman}/libexec/podman", "${pkgs.slirp4netns}/bin", "${pkgs.passt}/bin", "/usr/bin"]
    [engine.runtimes]
    crun = ["${pkgs.crun}/bin/crun"]
  '';
}
