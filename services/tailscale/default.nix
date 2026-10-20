# Run Tailscale on the host. Keep its node and SSH identity in the service data directory.
# The daemon needs host networking and login access.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  tailscale = pkgs.tailscale;
in
{
  # Ubuntu and sudo search /usr/local/bin first; the client follows the daemon version.
  systemd.tmpfiles.rules = [ "L+ /usr/local/bin/tailscale - - - - ${tailscale}/bin/tailscale" ];
  sops.secrets.tailscale-auth-key = {
    sopsFile = ../../secrets/mashu.sops.yaml;
    key = "tailscale_auth_key";
  };
  systemd.services.tailscaled = {
    description = "Tailscale node agent";
    wantedBy = [ "system-manager.target" ];
    wants = [ "network-pre.target" ];
    after = [
      "network-pre.target"
      "systemd-resolved.service"
    ];
    # Host networking tools and login utilities belong to Ubuntu, the daemon to Nix.
    environment.PATH = lib.mkForce "${tailscale}/bin:/usr/sbin:/usr/bin:/sbin:/bin";
    serviceConfig = {
      Type = "notify";
      ExecStart = "${tailscale}/bin/tailscaled --state=/var/lib/data/tailscale/tailscaled.state --socket=/run/tailscale/tailscaled.sock --port=41641";
      ExecStopPost = "${tailscale}/bin/tailscaled --cleanup";
      StateDirectory = "data/tailscale";
      StateDirectoryMode = "0700";
      RuntimeDirectory = "tailscale";
      RuntimeDirectoryMode = "0755";
      CacheDirectory = "tailscale";
      CacheDirectoryMode = "0750";
      Restart = "on-failure";
      RestartSec = 5;
      # SSH sessions need host login/PTY facilities; application sandboxes do not apply here.
      LimitCORE = 0;
    };
  };
  systemd.services.tailscale-enroll = {
    description = "Reconcile Tailscale SSH, routing, DNS and server tag";
    wantedBy = [ "system-manager.target" ];
    after = [
      "tailscaled.service"
      "sops-install-secrets.service"
    ];
    requires = [
      "tailscaled.service"
      "sops-install-secrets.service"
    ];
    path = [ tailscale ];
    script = ''
      export TS_AUTHKEY="$(< "$CREDENTIALS_DIRECTORY/auth-key")"
      exec ${pkgs.python3}/bin/python3 ${../../scripts/configure_tailscale.py}
    '';
    serviceConfig = import ../hardening.nix // {
      Type = "oneshot";
      RemainAfterExit = true;
      RuntimeDirectory = "tailscale-enroll";
      RuntimeDirectoryMode = "0700";
      LoadCredential = [ "auth-key:${config.sops.secrets.tailscale-auth-key.path}" ];
      TimeoutStartSec = "90s";
    };
  };
}
