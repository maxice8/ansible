# Native runner with a separate rootless Podman engine identity; jobs cannot read runner credentials.
# No host/root Docker socket is exposed. Engine images and workspaces are disposable cache.
{ config, lib, pkgs, ... }:
let
  podman = "${pkgs.podman}/bin/podman --storage-driver=vfs --root=/var/cache/runner-engine/containers --runroot=/run/runner-engine/storage";
  settings = {
    log.level = "info";
    runner = { file = "/var/lib/data/forgejo-runner/.runner"; capacity = 1; timeout = "3h"; shutdown_timeout = "3h";
      labels = [ "alpine:docker://alpine:latest" "docker:docker://docker:dind" "ubuntu-latest:docker://node:20-bookworm" ]; };
    cache.enabled = false;
    container = { network = ""; privileged = false; enable_ipv6 = false;
      options = "--cap-drop=ALL --security-opt=no-new-privileges";
      valid_volumes = []; docker_host = "unix:///run/runner-engine/podman.sock"; force_pull = false; };
    host.workdir_parent = "/var/cache/forgejo-runner/work";
  };
in {
  sops.secrets.forgejo-runner-registration-token = {
    sopsFile = ../secrets/mashu.sops.yaml; key = "forgejo_runner_registration_token";
  };
  environment.etc."forgejo-runner/config.json".text = builtins.toJSON settings;
  # Socket activation enforces group access; Podman's own rootless socket is always 0600.
  systemd.sockets.runner-engine = {
    wantedBy = [ "system-manager.target" ];
    after = [ "userborn.service" ];
    wants = [ "userborn.service" ];
    socketConfig = {
      ListenStream = "/run/runner-engine/podman.sock";
      SocketUser = "runner-engine"; SocketGroup = "forgejo-runner";
      SocketMode = "0660"; DirectoryMode = "0750"; RemoveOnStop = true;
    };
  };
  systemd.services.runner-engine-network = import ./egress.nix { inherit pkgs; name = "runner-engine"; uid = "{ 62009, 500000-565535 }"; publicTCP = null; publicUDP = null; };
  systemd.services.runner-engine = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "rootless-containers.service" "runner-engine-network.service" "runner-engine.socket" ];
    requires = [ "rootless-containers.service" "runner-engine-network.service" "runner-engine.socket" ];
    partOf = [ "rootless-containers.service" "runner-engine-network.service" ];
    path = [ pkgs.podman pkgs.slirp4netns pkgs.passt pkgs.crun pkgs.coreutils pkgs.util-linux ];
    environment = { HOME = "/var/cache/runner-engine"; XDG_RUNTIME_DIR = "/run/runner-engine";
      PATH = lib.mkForce "/usr/bin:/bin:${pkgs.lib.makeBinPath [ pkgs.podman pkgs.slirp4netns pkgs.passt pkgs.crun pkgs.coreutils pkgs.util-linux ]}"; };
    serviceConfig = {
      User = "runner-engine"; Group = "forgejo-runner";
      CacheDirectory = "runner-engine"; CacheDirectoryMode = "0700";
      RuntimeDirectory = "runner-engine"; RuntimeDirectoryMode = "0750";
      # The independently owned API socket must survive service restarts.
      RuntimeDirectoryPreserve = "yes";
      ExecStart = "${podman} system service --time=0";
      # The runner's group can use this socket, but the engine UID cannot read its 0700 state.
      UMask = "0007"; Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "3G"; TasksMax = 2048;
      NoNewPrivileges = false; ProtectHome = true; PrivateTmp = true;
      # Keep DNS helpers in this cgroup instead of requesting a separate user scope.
      TemporaryFileSystem = [ "/run/systemd:ro" ];
      # /etc/resolv.conf points into resolved's runtime directory on Ubuntu.
      BindReadOnlyPaths = [ "/run/systemd/resolve" ];
      # Rootless networking must write tunables in its own network namespace.
      # The host namespace remains protected by ordinary UID/capability checks.
      # A visible parent /proc is required for the container runtime to mount its own.
      ProtectKernelTunables = false; ProtectKernelModules = false; ProtectKernelLogs = false;
      ProtectSystem = "strict"; ReadWritePaths = [ "/var/cache/runner-engine" "/run/runner-engine" ];
    };
  };
  systemd.services.forgejo-runner-network = import ./egress.nix { inherit pkgs; name = "forgejo-runner"; uid = 974; };
  systemd.services.forgejo-runner = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "forgejo.service" "runner-engine.service" "forgejo-runner-network.service" "sops-install-secrets.service" ];
    requires = [ "runner-engine.service" "forgejo-runner-network.service" "sops-install-secrets.service" ];
    partOf = [ "forgejo-runner-network.service" ];
    path = [ pkgs.git pkgs.openssh ];
    preStart = ''
      # Feed first registration through stdin so its secret never appears in argv.
      if [ ! -s /var/lib/data/forgejo-runner/.runner ]; then
        {
          printf '%s\n' 'https://git.maxice8.com'
          printf '%s\n' "$(< "$CREDENTIALS_DIRECTORY/registration-token")"
          printf '%s\n' 'mashu-runner' ""
        } | ${pkgs.forgejo-runner}/bin/forgejo-runner register --config /etc/forgejo-runner/config.json
      fi
    '';
    environment = { HOME = "/var/lib/data/forgejo-runner"; DOCKER_HOST = "unix:///run/runner-engine/podman.sock";
      SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"; };
    serviceConfig = import ./hardening.nix // {
      User = "forgejo-runner"; Group = "forgejo-runner";
      StateDirectory = "data/forgejo-runner"; StateDirectoryMode = "0700";
      CacheDirectory = "forgejo-runner"; WorkingDirectory = "/var/lib/data/forgejo-runner";
      LoadCredential = [ "registration-token:${config.sops.secrets.forgejo-runner-registration-token.path}" ];
      ExecStart = "${pkgs.forgejo-runner}/bin/forgejo-runner daemon --config /etc/forgejo-runner/config.json";
      Restart = "on-failure"; RestartSec = 5; TimeoutStopSec = "3h";
      MemoryMax = "1G"; TasksMax = 256;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" ];
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
    };
  };
}
