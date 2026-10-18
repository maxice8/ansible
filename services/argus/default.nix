# Release Argus tracks application releases against Nix-selected or HTTP-reported versions.
{ config, lib, pkgs, ... }:
let
  argus = pkgs.callPackage ../../pkgs/release-argus.nix {};
  selected = {
    traefik-image = { repo = "traefik/traefik"; version = (pkgs.callPackage ../../pkgs/traefik.nix {}).version; };
    argus = { repo = "release-argus/Argus"; version = argus.version; };
    asf = { repo = "JustArchiNET/ArchiSteamFarm"; version = (pkgs.callPackage ../../pkgs/archisteamfarm.nix {}).version; };
    forgejo-runner = { repo = "forgejo/runner"; version = pkgs.forgejo-runner.version; };
    pocket-id = { repo = "pocket-id/pocket-id"; version = (pkgs.callPackage ../../pkgs/pocket-id.nix {}).version; };
    pomerium = { repo = "pomerium/pomerium"; version = (pkgs.callPackage ../../pkgs/pomerium.nix {}).version; };
    syncthing = { repo = "syncthing/syncthing"; version = (pkgs.callPackage ../../pkgs/syncthing.nix {}).version; };
    forgejo = { repo = "forgejo/forgejo"; version = (pkgs.callPackage ../../pkgs/forgejo.nix {}).version; };
  };
  # "Manual" versions come from selected Nix packages, not running processes.
  # Services with live version probes override this assumption below.
  manual = lib.mapAttrs (_: entry: {
    comment = "Configured in the active Nix generation; manual version, not a process probe";
    notify.discord = {}; # Use the shared Discord notifier defined below.
    latest_version = {
      type = "github";
      url = entry.repo;
      url_commands = [{ type = "regex"; regex = "^v?([0-9.]+)$"; }];
    };
    deployed_version = { type = "manual"; inherit (entry) version; };
  }) selected;

  # Query Forgejo's own latest-release API for both the server and its runner.
  forgejoLatest = repo: {
    type = "url";
    url = "https://code.forgejo.org/api/v1/repos/forgejo/${repo}/releases/latest";
    url_commands = [{
      type = "regex";
      regex = ''"tag_name":"v?([0-9.]+)"'';
    }];
  };

  # Dashboard access, shared release-check policy, alert delivery and service probes.
  settings = {
    settings = {
      data = {
        database_file = "/var/lib/data/argus/argus.db";
        # Prevent config-file rewrites; approval/release state in SQLite stays writable.
        readonly = true;
      };
      web = {
        listen_host = "127.0.0.1";
        listen_port = 8081;
        # Keep service definitions in Nix; dashboard approval/skipping remains available.
        disabled_routes = [ "order_edit" "service_create" "service_update" "service_delete" ];
      };
    };
    # Check/approval policy shared by all monitored applications.
    defaults.service = {
      options = {
        interval = "1h";
        semantic_versioning = true;
      };
      # Approval records a decision in Argus; it does not deploy a Nix update.
      dashboard.auto_approve = false;
    };
    notify.discord = {
      type = "discord";
      url_fields = {
        # Argus resolves these placeholders from SOPS-backed runtime credentials.
        Token = "\${ARGUS_DISCORD_TOKEN}";
        WebhookID = "\${ARGUS_DISCORD_WEBHOOK_ID}";
      };
    };

    # Exceptions for live version probes, Forgejo-hosted releases and ASF's version format.
    service = manual // {
      forgejo = manual.forgejo // {
        comment = "Running Forgejo HTTP version";
        latest_version = forgejoLatest "forgejo";
        deployed_version = {
          type = "url";
          url = "http://127.0.0.1:3000/api/v1/version";
          json = "version";
          regex = "^([0-9.]+)";
        };
      };
      forgejo-runner = manual.forgejo-runner // {
        # Change only the upstream query; its selected Nix version remains manual.
        latest_version = forgejoLatest "runner";
      };
      asf = manual.asf // {
        # ASF uses four-part versions, outside SemVer's three-part format.
        options.semantic_versioning = false;
      };
    };
  };

  # Credential filenames map to keys in the encrypted SOPS document.
  credentials = {
    discord-token = "argus_discord_token";
    discord-webhook-id = "argus_discord_webhook_id";
    github-token = "argus_github_token";
  };
  # Argus discovers service ordering from YAML lines, even though JSON decodes.
  configFile = (pkgs.formats.yaml {}).generate "argus-config.yaml" settings;
  start = pkgs.writeShellScript "argus-start" ''
    set -euo pipefail
    export ARGUS_DISCORD_TOKEN="$(< "$CREDENTIALS_DIRECTORY/discord-token")"
    export ARGUS_DISCORD_WEBHOOK_ID="$(< "$CREDENTIALS_DIRECTORY/discord-webhook-id")"
    export ARGUS_SERVICE_LATEST_VERSION_GITHUB_ACCESS_TOKEN="$(< "$CREDENTIALS_DIRECTORY/github-token")"
    exec ${argus}/bin/argus -config.file=${configFile}
  '';
  unit = pkgs.writeText "argus.service" (lib.generators.toINI { listsAsDuplicateKeys = true; } {
    Unit = {
      Description = "Release Argus portable service";
      After = "network-online.target userborn.service sops-install-secrets.service argus-network.service";
      Requires = "sops-install-secrets.service argus-network.service";
      PartOf = "argus-network.service";
    };
    Service = import ../hardening.nix // {
      # Numeric host identity preserves state ownership and UID-scoped firewall rules.
      User = "5007"; Group = "5007";
      StateDirectory = "data/argus"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/argus";
      LoadCredential = lib.mapAttrsToList (name: _: "${name}:${config.sops.secrets."argus-${name}".path}") credentials;
      ExecStart = start;
      Environment = "SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
      Restart = "on-failure"; RestartSec = 5; MemoryMax = "128M"; TasksMax = 128;
      ProtectKernelLogs = true; ProtectProc = "invisible"; ProcSubset = "pid";
      RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = "AF_UNIX AF_INET AF_INET6 AF_NETLINK";
      LockPersonality = true; MemoryDenyWriteExecute = true; SystemCallArchitectures = "native";
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = "ipv4:tcp:8081";
    };
    Install.WantedBy = "system-manager.target";
  });
  # Bundle the unit and its referenced Nix runtime closure into a read-only image.
  image = (pkgs.portableService {
    pname = "argus"; version = argus.version;
    description = "Mashu Release Argus";
    units = [ unit ];
    # The hidden config reference creates the state mountpoint in the read-only image.
    symlinks = [{ object = configFile; symlink = "var/lib/data/argus/.image-config"; }];
  }).overrideAttrs (old: {
    # Keep one operational name; Nix's store hash still distinguishes image builds.
    buildCommand = old.buildCommand + ''
      mv "$out/argus_${argus.version}.raw" "$out/argus.raw"
    '';
  });
in {
  sops.secrets = lib.mapAttrs' (name: key: lib.nameValuePair "argus-${name}" {
    sopsFile = ../../secrets/mashu.sops.yaml; inherit key; restartUnits = [ "argus.service" ];
  }) credentials;
  systemd.services.argus-network = import ../firewall.nix { inherit pkgs; name = "argus"; uid = 5007; localTCP = [ 3000 19999 ]; };
  build.scripts.argus = import ../activate-portable.nix {
    inherit pkgs image;
    name = "argus";
    healthURL = "http://127.0.0.1:8081/api/v1/healthcheck";
  };
}
