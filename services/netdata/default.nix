# Monitor the host and cgroups with an unprivileged Netdata service.
# Do not expose privileged plugin wrappers or a Docker socket.
{ config, pkgs, ... }:
let
  netdata = pkgs.netdata;
  # Stock notifications otherwise put the webhook token in curl's public argv.
  notifyCurl = pkgs.writeShellScript "netdata-discord-curl" ''
    args=()
    for argument in "$@"; do
      if [ "$argument" = https://discord.invalid/slack ]; then
        args+=(--variable "hook@/run/credentials/netdata.service/discord-url" --expand-url '{{hook:trim}}/slack')
      else
        args+=("$argument")
      fi
    done
    exec ${pkgs.curl}/bin/curl "''${args[@]}"
  '';
in
{
  sops.secrets.netdata-discord-url = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "netdata_discord_url";
    restartUnits = [ "netdata.service" ];
  };
  sops.secrets.netdata-heartbeat-url = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "netdata_heartbeat_url";
  };
  environment.etc."netdata/netdata.conf".text = ''
    [global]
      hostname = mashu
      run as user = netdata
    [directories]
      config = /etc/netdata
      stock config = ${netdata}/share/netdata/conf.d
      cache = /var/lib/data/netdata/cache
      lib = /var/lib/data/netdata/lib
      log = /var/log/netdata
      web = ${netdata}/share/netdata/web
      plugins = ${netdata}/libexec/netdata/plugins.d
    [db]
      mode = dbengine
      storage tiers = 2
      dbengine tier 0 retention size = 1GiB
      dbengine tier 0 retention time = 7d
      dbengine tier 1 retention size = 1GiB
      dbengine tier 1 retention time = 30d
    [web]
      bind to = 127.0.0.1:19999
      allow connections from = localhost
    [plugins]
      proc = yes
      cgroups = yes
      apps = no
      tc = no
      python.d = no
      charts.d = no
      go.d = no
      node.d = no
  '';
  environment.etc."netdata/health_alarm_notify.conf".text = ''
    SEND_EMAIL="NO"
    SEND_DISCORD="YES"
    # The stock helper appends /slack; the wrapper expands the credential inside curl.
    DISCORD_WEBHOOK_URL="https://discord.invalid"
    curl="${notifyCurl}"
    DEFAULT_RECIPIENT_DISCORD="netdata-alerts"
  '';
  environment.etc."nftables/netdata.nft".source = ./firewall.nft;
  systemd.services.netdata-network = import ../firewall.nix {
    inherit pkgs;
    name = "netdata";
    policy = ./firewall.nft;
  };
  systemd.services.netdata = {
    wantedBy = [ "system-manager.target" ];
    after = [
      "network-online.target"
      "userborn.service"
      "sops-install-secrets.service"
      "netdata-network.service"
    ];
    requires = [
      "sops-install-secrets.service"
      "netdata-network.service"
    ];
    partOf = [ "netdata-network.service" ];
    restartTriggers = [
      config.environment.etc."netdata/netdata.conf".source
      config.environment.etc."netdata/health_alarm_notify.conf".source
    ];
    path = [
      pkgs.curl
      pkgs.gawk
      pkgs.iproute2
      pkgs.procps
      pkgs.bash
      pkgs.util-linux
    ];
    environment = {
      DO_NOT_TRACK = "1";
      NETDATA_PIPENAME = "/run/netdata/ipc";
    };
    serviceConfig = import ../hardening.nix // {
      User = "netdata";
      Group = "netdata";
      StateDirectory = [
        "data/netdata"
        "data/netdata/cache"
        "data/netdata/lib"
      ];
      StateDirectoryMode = "0700";
      LogsDirectory = "netdata";
      RuntimeDirectory = "netdata";
      LoadCredential = [ "discord-url:${config.sops.secrets.netdata-discord-url.path}" ];
      ExecStart = "${netdata}/bin/netdata -D -P /run/netdata/netdata.pid -c /etc/netdata/netdata.conf";
      Restart = "on-failure";
      RestartSec = 5;
      MemoryMax = "1G";
      TasksMax = 256;
      ProtectKernelLogs = true;
      RestrictNamespaces = true;
      RestrictRealtime = true;
      RestrictAddressFamilies = [
        "AF_UNIX"
        "AF_INET"
        "AF_INET6"
        "AF_NETLINK"
      ];
      IPAddressDeny = [
        "169.254.0.0/16"
        "fe80::/10"
      ];
      SocketBindDeny = [
        "ipv4:tcp:1-65535"
        "ipv6:tcp:1-65535"
        "ipv4:udp:1-65535"
        "ipv6:udp:1-65535"
      ];
      SocketBindAllow = [ "ipv4:tcp:19999" ];
    };
  };
  systemd.services.netdata-heartbeat = {
    after = [
      "netdata.service"
      "sops-install-secrets.service"
      "netdata-network.service"
    ];
    requires = [
      "sops-install-secrets.service"
      "netdata-network.service"
    ];
    environment.CURL_CA_BUNDLE = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
    script = ''
      ${pkgs.curl}/bin/curl -fsS --max-time 10 --output /dev/null --proto '=https' \
        --variable "heartbeat@$CREDENTIALS_DIRECTORY/url" --expand-url '{{heartbeat:trim}}'
    '';
    serviceConfig = import ../hardening.nix // {
      Type = "oneshot";
      User = "netdata";
      Group = "netdata";
      # Skip external pings while the collector is paused for maintenance.
      ExecCondition = "${pkgs.curl}/bin/curl -fsS --max-time 10 --output /dev/null http://127.0.0.1:19999/api/v1/info";
      LoadCredential = [ "url:${config.sops.secrets.netdata-heartbeat-url.path}" ];
      TimeoutStartSec = 30;
    };
  };
  systemd.timers.netdata-heartbeat = {
    wantedBy = [ "system-manager.target" ];
    timerConfig = {
      OnActiveSec = "1min";
      OnUnitActiveSec = "1min";
      AccuracySec = "5s";
    };
  };
}
