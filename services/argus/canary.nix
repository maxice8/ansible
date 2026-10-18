# Separate real application canary; portablectl owns this unit, not System Manager.
{ pkgs }:
let
  argus = pkgs.callPackage ../../pkgs/release-argus.nix {};
  configFile = pkgs.writeText "argus-canary.json" (builtins.toJSON {
    settings = {
      data = { database_file = "/var/lib/argus-canary/argus.db"; readonly = true; };
      web = {
        listen_host = "127.0.0.1"; listen_port = 18081;
        disabled_routes = [ "order_edit" "service_create" "service_update" "service_delete" ];
      };
    };
    service.argus-canary = {
      name = "Portable Argus canary";
      options.active = false;
      latest_version = { type = "github"; url = "release-argus/Argus"; };
      deployed_version = { type = "manual"; version = argus.version; };
    };
  });
  unit = pkgs.writeText "argus-canary.service" (pkgs.lib.generators.toINI {
    listsAsDuplicateKeys = true;
  } {
    Unit.Description = "Isolated Release Argus portable canary";
    Service = import ../hardening.nix // {
      ExecStart = "${argus}/bin/argus -config.file=${configFile}";
      Environment = "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      DynamicUser = true;
      StateDirectory = "argus-canary"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/argus-canary";
      Restart = "on-failure"; RestartSec = 5;
      MemoryMax = "128M"; TasksMax = 128;
      ProtectKernelLogs = true; ProtectProc = "invisible"; ProcSubset = "pid";
      RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = "AF_UNIX AF_INET AF_NETLINK";
      LockPersonality = true; MemoryDenyWriteExecute = true;
      SystemCallArchitectures = "native";
      IPAddressDeny = "any"; IPAddressAllow = "localhost";
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = "ipv4:tcp:18081";
    };
    Install.WantedBy = "multi-user.target";
  });
in pkgs.portableService {
  pname = "argus-canary";
  version = argus.version;
  description = "Release Argus portable canary with isolated state and no active pollers";
  units = [ unit ];
  # Pre-create the state mountpoint; SquashFS cannot add directories at startup.
  symlinks = [{ object = configFile; symlink = "var/lib/argus-canary/.image-config"; }];
}
