# Override DNS only inside application mount namespaces; host/Tailscale keep resolved.
{ config, lib, pkgs, ... }:
let
  resolver = config.environment.etc."homelab/resolv.conf".source;
  # resolved replaces its runtime files; isolate their parent directory as well.
  resolverDirectory = pkgs.linkFarm "application-resolved" [
    { name = "stub-resolv.conf"; path = resolver; }
    { name = "resolv.conf"; path = resolver; }
  ];
  native = [  ];
in {
  environment.etc."homelab/resolv.conf".text = ''
    nameserver 127.0.0.1
    search neko-great.ts.net
    options edns0
  '';
  system-manager.preActivationAssertions.applicationDNS = {
    enable = true;
    # Native units replace the resolved runtime directory inside their own namespace.
    script = ''
      test "$(/usr/bin/readlink -f /etc/resolv.conf)" = /run/systemd/resolve/stub-resolv.conf
    '';
  };
  systemd.services = lib.genAttrs native (_: {
    wants = [ "unbound.service" ];
    after = [ "unbound.service" "systemd-resolved.service" ];
    restartTriggers = [ resolverDirectory ];
    serviceConfig.BindReadOnlyPaths = [
      "${resolverDirectory}:/run/systemd/resolve"
    ];
  });
}
