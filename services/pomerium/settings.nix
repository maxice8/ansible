# Configure Pomerium access rules. Traefik provides TLS.
# Each protected application has a distinct loopback port, including Argus on 8081.
let
  route = name: description: host: port: {
    inherit name description;
    from = "https://${host}.mashu.maxice8.com";
    to = "http://127.0.0.1:${toString port}";
    policy = [ { allow.or = [ { authenticated_user = true; } ]; } ];
  };
in
{
  insecure_server = true;
  address = "127.0.0.1:8080";
  grpc_address = "127.0.0.1:5443";
  health_check_addr = "127.0.0.1:28080";
  idp_provider = "oidc";
  idp_provider_url = "https://id.maxice8.com";
  authenticate_service_url = "https://pomerium.maxice8.com";
  # A single instance can persist sessions without introducing another database.
  databroker_storage_type = "file";
  # Pebble opens the database's parent for directory synchronization; keep it private
  # inside our owned state directory rather than granting read access to /var/lib/data.
  databroker_storage_connection_string = "file:///var/lib/data/pomerium/databroker";
  # Even a single-node databroker opens a Raft listener; its empty default binds *:0.
  databroker_raft_bind_address = "127.0.0.1:0";
  # Exclude URLs, queries, identity claims and headers from routine access logs.
  access_log_fields = [
    "authority"
    "method"
    "response-code"
    "duration"
  ];
  authorize_log_fields = [
    "host"
    "method"
  ];
  routes = [
    (route "ArchiSteamFarm" "Steam Accounts" "asf" 1242)
    (route "Syncthing" "File Synchronization" "syncthing" 8384)
    (route "Netdata" "System Monitoring" "netdata" 19999)
    (route "Backrest" "Backup Management" "backrest" 9898)
    ((route "Argus" "Release Monitoring" "argus" 8081) // { allow_websockets = true; })
  ];
}
