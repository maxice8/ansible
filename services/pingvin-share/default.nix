# Rootless, digest-pinned fork image; only uploads/images are durable application state.
# The container has no engine socket, host capabilities or application-data access outside its mounts.
{ lib, pkgs, ... }:
let
  image = pkgs.callPackage ../../pkgs/pingvin-share-image.nix {};
  podman = "${pkgs.podman}/bin/podman --storage-driver=vfs --root=/var/cache/pingvin-share/containers --runroot=/run/pingvin-share/storage";
in {
  systemd.services.pingvin-share-network = import ../firewall.nix {
    inherit pkgs; name = "pingvin-share"; uid = "{ 5006, 600000-665535 }";
    publicDNS = [ "1.1.1.1" "1.0.0.1" ];
  };
  systemd.services.pingvin-share = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "rootless-containers.service" "pingvin-share-network.service" ];
    requires = [ "rootless-containers.service" "pingvin-share-network.service" ];
    partOf = [ "rootless-containers.service" "pingvin-share-network.service" ];
    path = [ pkgs.podman pkgs.slirp4netns pkgs.passt pkgs.crun pkgs.coreutils pkgs.util-linux ];
    environment = { HOME = "/var/cache/pingvin-share"; XDG_RUNTIME_DIR = "/run/pingvin-share";
      PATH = lib.mkForce "/usr/bin:/bin:${pkgs.lib.makeBinPath [ pkgs.podman pkgs.slirp4netns pkgs.passt pkgs.crun pkgs.coreutils pkgs.util-linux ]}"; };
    serviceConfig = {
      User = "pingvin-share"; Group = "pingvin-share";
      StateDirectory = [ "data/pingvin-share" "data/pingvin-share/data" "data/pingvin-share/images" ]; StateDirectoryMode = "0700";
      CacheDirectory = "pingvin-share"; CacheDirectoryMode = "0700";
      RuntimeDirectory = "pingvin-share"; RuntimeDirectoryMode = "0700";
      ExecStartPre = "${podman} load -i ${image}";
      # Image health timers require a user bus; this system unit owns the lifecycle.
      ExecStart = "${podman} run --rm --replace --pull=never --name=pingvin-share --cgroups=disabled --no-healthcheck --health-interval=disable --log-driver=k8s-file --userns=keep-id:uid=1000,gid=1000 --user=1000:1000 --cap-drop=all --security-opt=no-new-privileges --network=slirp4netns:allow_host_loopback=false --publish=127.0.0.1:3001:3000 --env=TRUST_PROXY=true --volume=/var/lib/data/pingvin-share/data:/opt/app/backend/data:rw --volume=/var/lib/data/pingvin-share/images:/opt/app/frontend/public/img:rw smp46/pingvin-share-x:v1.22.4";
      ExecStop = "${podman} stop --time=30 pingvin-share";
      Restart = "on-failure"; RestartSec = 5; TimeoutStartSec = "10min"; TimeoutStopSec = 45;
      MemoryMax = "768M"; TasksMax = 512;
      # uidmap must gain its narrowly scoped setuid privilege; the container itself has NNP.
      NoNewPrivileges = false; ProtectHome = true; PrivateTmp = true;
      # Rootless networking must write tunables in its own network namespace.
      # The host namespace remains protected by ordinary UID/capability checks.
      # A visible parent /proc is required for the container runtime to mount its own.
      ProtectKernelTunables = false; ProtectKernelModules = false; ProtectKernelLogs = false;
      ProtectSystem = "strict"; ReadWritePaths = [ "/var/cache/pingvin-share" "/run/pingvin-share" "/var/lib/data/pingvin-share" ];
      UMask = "0077";
    };
  };
}
