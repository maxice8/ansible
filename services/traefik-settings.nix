# Final native ingress configuration, shared by the service and its VM checks.
# All backends are local services; Kubernetes transition routes are operator state.
let
  backends = {
    "git.maxice8.com" = "http://127.0.0.1:3000";
    "id.maxice8.com" = "http://127.0.0.1:1411";
    "share.mashu.maxice8.com" = "http://127.0.0.1:3001";
    "pomerium.maxice8.com" = "http://127.0.0.1:8080";
    "argus.mashu.maxice8.com" = "http://127.0.0.1:8080";
    "asf.mashu.maxice8.com" = "http://127.0.0.1:8080";
    "backrest.mashu.maxice8.com" = "http://127.0.0.1:8080";
    "netdata.mashu.maxice8.com" = "http://127.0.0.1:8080";
    "syncthing.mashu.maxice8.com" = "http://127.0.0.1:8080";
  };
in {
  static = {
    global = { checkNewVersion = false; sendAnonymousUsage = false; };
    log.level = "INFO";
    # Keep credentials, query strings and request headers out of routine logs.
    accessLog = {
      format = "json";
      fields = { defaultMode = "drop"; names = {
        StartUTC = "keep"; Duration = "keep"; RequestHost = "keep";
        RequestMethod = "keep"; DownstreamStatus = "keep"; RouterName = "keep";
      }; };
    };
    entryPoints = {
      web = {
        address = ":80";
        # Reject header aliases that could spoof identity headers at a backend.
        http.aliasHeadersStrategy = "reject";
        http.redirections.entryPoint = { to = ":443"; scheme = "https"; permanent = true; };
      };
      websecure = {
        address = ":443";
        http.aliasHeadersStrategy = "reject";
        http.tls = {
          certResolver = "letsencrypt";
          # One certificate request covers all public names, including the wildcard.
          domains = [{ main = "mashu.maxice8.com"; sans = [
            "*.mashu.maxice8.com" "git.maxice8.com" "id.maxice8.com" "pomerium.maxice8.com"
          ]; }];
        };
      };
      health = { address = "127.0.0.1:9080"; http.aliasHeadersStrategy = "reject"; };
    };
    ping.entryPoint = "health";
    providers.file = { filename = "/etc/traefik/routes.yaml"; watch = true; };
    certificatesResolvers.letsencrypt.acme = {
      email = "thinkabit.ukim@gmail.com";
      storage = "/var/lib/data/traefik/acme.json";
      dnsChallenge = { provider = "cloudflare"; resolvers = [ "1.1.1.1:53" "1.0.0.1:53" ]; };
    };
  };
  dynamic = {
    http = {
      # mapAttrs preserves each hostname as the matching router/service identifier.
      routers = builtins.mapAttrs (host: _: {
        rule = "Host(`${host}`)";
        entryPoints = [ "websecure" ];
        service = host;
        # Omit router-level TLS: even {} would suppress the entrypoint ACME defaults.
      }) backends;
      services = builtins.mapAttrs (_: url: { loadBalancer.servers = [{ inherit url; }]; }) backends;
    };
    tls.options.default.minVersion = "VersionTLS12";
  };
}
