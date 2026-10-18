# Release Argus tracks the native applications; no Kubernetes/chart/Git-master version probes.
# Manual entries explicitly describe the active Nix selection, not a runtime health claim.
{ config, lib, pkgs, ... }:
let
  argus = pkgs.callPackage ../pkgs/release-argus.nix {};
  selected = {
    traefik-image = { repo = "traefik/traefik"; version = (pkgs.callPackage ../pkgs/traefik.nix {}).version; };
    argus = { repo = "release-argus/Argus"; version = argus.version; };
    asf = { repo = "JustArchiNET/ArchiSteamFarm"; version = (pkgs.callPackage ../pkgs/archisteamfarm.nix {}).version; };
    backrest = { repo = "garethgeorge/backrest"; version = (pkgs.callPackage ../pkgs/backrest.nix {}).version; };
    forgejo-runner = { repo = "forgejo/runner"; version = pkgs.forgejo-runner.version; };
    pingvin-share = { repo = "smp46/pingvin-share-x"; version = lib.removePrefix "v" (pkgs.callPackage ../pkgs/pingvin-share-image.nix {}).imageTag; };
    pocket-id = { repo = "pocket-id/pocket-id"; version = (pkgs.callPackage ../pkgs/pocket-id.nix {}).version; };
    pomerium = { repo = "pomerium/pomerium"; version = (pkgs.callPackage ../pkgs/pomerium.nix {}).version; };
    syncthing = { repo = "syncthing/syncthing"; version = (pkgs.callPackage ../pkgs/syncthing.nix {}).version; };
    netdata-agent = { repo = "netdata/netdata"; version = pkgs.netdata.version; };
    forgejo = { repo = "forgejo/forgejo"; version = (pkgs.callPackage ../pkgs/forgejo.nix {}).version; };
  };
  manual = lib.mapAttrs (_: entry: {
    comment = "Configured in the active Nix generation; manual version, not a process probe";
    notify.discord = {};
    latest_version = {
      type = "github"; url = entry.repo;
      url_commands = [{ type = "regex"; regex = "^v?([0-9.]+)$"; }];
    };
    deployed_version = { type = "manual"; inherit (entry) version; };
  }) selected;
  forgejoLatest = repo: { type = "url"; url = "https://code.forgejo.org/api/v1/repos/forgejo/${repo}/releases/latest";
    url_commands = [{ type = "regex"; regex = ''"tag_name":"v?([0-9.]+)"''; }]; };
  settings = {
    settings = { data = { database_file = "/var/lib/data/argus/argus.db"; readonly = true; };
      web = { listen_host = "127.0.0.1"; listen_port = 8081;
        disabled_routes = [ "order_edit" "service_create" "service_update" "service_delete" ]; }; };
    defaults.service = { options = { interval = "1h"; semantic_versioning = true; };
      dashboard.auto_approve = false; };
    notify.discord = { type = "discord"; url_fields = { Token = "\${ARGUS_DISCORD_TOKEN}"; WebhookID = "\${ARGUS_DISCORD_WEBHOOK_ID}"; }; };
    service = manual // {
      forgejo = manual.forgejo // {
        comment = "Running Forgejo HTTP version"; latest_version = forgejoLatest "forgejo";
        deployed_version = { type = "url"; url = "http://127.0.0.1:3000/api/v1/version"; json = "version"; regex = "^([0-9.]+)"; };
      };
      forgejo-runner = manual.forgejo-runner // { latest_version = forgejoLatest "runner"; };
      netdata-agent = manual.netdata-agent // {
        comment = "Running native host collector HTTP version";
        deployed_version = { type = "url"; url = "http://127.0.0.1:19999/api/v1/info"; json = "version"; regex = "^v?([0-9.]+)"; };
      };
      asf = manual.asf // { options.semantic_versioning = false; };
    };
  };
  credentials = { discord-token = "argus_discord_token"; discord-webhook-id = "argus_discord_webhook_id"; github-token = "argus_github_token"; };
in {
  sops.secrets = lib.mapAttrs' (name: key: lib.nameValuePair "argus-${name}" {
    sopsFile = ../secrets/mashu.sops.yaml; inherit key; restartUnits = [ "argus.service" ];
  }) credentials;
  environment.etc."argus/config.json".text = builtins.toJSON settings;
  systemd.services.argus-network = import ./egress.nix { inherit pkgs; name = "argus"; uid = 911; localTCP = [ 3000 19999 ]; };
  systemd.services.argus = {
    wantedBy = [ "system-manager.target" ];
    after = [ "network-online.target" "userborn.service" "sops-install-secrets.service" "argus-network.service" ];
    requires = [ "sops-install-secrets.service" "argus-network.service" ]; partOf = [ "argus-network.service" ];
    restartTriggers = [ config.environment.etc."argus/config.json".source ];
    script = ''
      export ARGUS_DISCORD_TOKEN="$(< "$CREDENTIALS_DIRECTORY/discord-token")"
      export ARGUS_DISCORD_WEBHOOK_ID="$(< "$CREDENTIALS_DIRECTORY/discord-webhook-id")"
      export ARGUS_SERVICE_LATEST_VERSION_ACCESS_TOKEN="$(< "$CREDENTIALS_DIRECTORY/github-token")"
      exec ${argus}/bin/argus -config.file=/etc/argus/config.json
    '';
    environment.SSL_CERT_FILE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    serviceConfig = import ./hardening.nix // {
      User = "argus"; Group = "argus"; StateDirectory = "data/argus"; StateDirectoryMode = "0700";
      WorkingDirectory = "/var/lib/data/argus";
      LoadCredential = lib.mapAttrsToList (name: _: "${name}:${config.sops.secrets."argus-${name}".path}") credentials;
      Restart = "on-failure"; RestartSec = 5; MemoryMax = "128M"; TasksMax = 128;
      ProtectKernelLogs = true; RestrictNamespaces = true; RestrictRealtime = true;
      RestrictAddressFamilies = [ "AF_UNIX" "AF_INET" "AF_INET6" "AF_NETLINK" ];
      IPAddressDeny = [ "169.254.0.0/16" "fe80::/10" ];
      SocketBindDeny = [ "ipv4:tcp:1-65535" "ipv6:tcp:1-65535" "ipv4:udp:1-65535" "ipv6:udp:1-65535" ];
      SocketBindAllow = [ "ipv4:tcp:8081" ];
    };
  };
}
