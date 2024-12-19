job "vaultwarden" {
  datacenters = ["dc1"]
  type        = "service"

  group "vaultwarden-group" {
    count = 1

    network {
      mode = "bridge"
      hostname = "vault"

      port "web" {
        static = 80
        host_network = "tailscale"
      }
    }

    volume "vaultwarden-volume" {
      type      = "host"
      read_only = false
      source    = "vaultwarden-data"
    }

    volume "tailscale-volume" {
      type = "host"
      read_only = false
      source = "vaultwarden-tailscale-data"
    }

    task "vaultwarden" {
      driver = "docker"

      service {
        name = "vaultwarden"
        port = "web"
        check {
          name = "Web check"
          path = "/"
          type = "http"
          port = "web"
          interval = "5s"
          timeout = "2s"
        }
      }

      logs {
        max_files     = 10
        max_file_size = 10 # In MB
      }

      volume_mount {
        volume      = "vaultwarden-volume"
        destination = "/data/"
        read_only   = false
      }

      config {
        image = "vaultwarden/server"
      }

      env {
        EXPERIMENTAL_CLIENT_FEATURE_FLAGS = "fido2-vault-credentials,ssh-key-vault-item,ssh-agent"
        SIGNUPS_ALLOWED                   = "False"
      }

      template {
        destination = "/vaultwarden.env"
        env = true
        data        = <<EOF
DOMAIN=https://vault.{{ with nomadVar "tailscale" }}{{ .tailnet }}{{ end }}.ts.net
ADMIN_TOKEN={{ with nomadVar "vaultwarden" }}{{ .admin_token }}{{ end }}
EOF
      }
    }

    task "tailscale" {
      driver = "docker" 

      volume_mount {
        volume      = "tailscale-volume"
        destination = "/var/lib/tailscale/"
        read_only   = false
      }

      template {
        destination = "/tailscale.env"
        env = true
        data        = <<EOF
TS_AUTHKEY={{ with nomadVar "tailscale" }}{{ .clientsecret }}{{ end }}?ephemeral=false
EOF
      }

      lifecycle {
        hook = "prestart"
        sidecar = true
      }

      logs {
        max_files     = 10
        max_file_size = 10 # In MB
      }

      config {
        image    = "tailscale/tailscale:latest"

        volumes = [
          "secrets/serve.json:${NOMAD_SECRETS_DIR}/serve.json:ro"
        ]

        devices = [
          { host_path = "/dev/net/tun", container_path = "/dev/net/tun" }
        ]

        cap_add = ["NET_ADMIN"]
      }
        
      template {
        destination = "secrets/serve.json"
        change_mode = "restart"
        data = <<EOF
{
    "TCP": {
        "443": {
            "HTTPS": true
        }
    },
    "Web": {
        "${TS_CERT_DOMAIN}:443": {
            "Handlers": {
                "/": {
                    "Proxy": "http://127.0.0.1:80"
                }
            }
        }
    },
    "AllowFunnel": {
        "${TS_CERT_DOMAIN}:443": true
    }
}
EOF
      }

      env {
        TS_EXTRA_ARGS   = "--advertise-tags=tag:nomad"
        TS_SERVE_CONFIG = "${NOMAD_SECRETS_DIR}/serve.json"
        TS_STATE_DIR    = "/var/lib/tailscale"
        TS_USERSPACE    = "false"
      }
    }
  }
}
