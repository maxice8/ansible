# tasks/caddy.py
import io
import urllib.request

from pyinfra import host
from pyinfra.operations import files, server, systemd

from utils import ShellFact, apply_tmpfiles, deploy_quadlet, ensure_secret

apply_tmpfiles(
    "caddy", "d /etc/caddy 0755 root root -\nd /var/log/caddy 0755 root root -"
)

image_exists = host.get_fact(
    ShellFact,
    "podman image exists localhost/caddy-custom:latest && echo 'yes' || echo 'no'",
)

containerfile_content = """FROM docker.io/library/caddy:builder AS builder
RUN xcaddy build --with github.com/hslatman/caddy-crowdsec-bouncer
FROM docker.io/library/caddy:alpine
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
"""
cf_changed = files.put(
    name="Copy Containerfile for custom build",
    src=io.StringIO(containerfile_content),
    dest="/etc/caddy/Containerfile",
    user="root",
    group="root",
    mode="0644",
).changed

api_key = host.data.get("caddy_crowdsec_api_key", "")
svcs = host.data.configured_services

# Caddyfile Generation
caddy_blocks = []
if api_key:
    caddy_blocks.append(
        "    crowdsec {\n        api_key {$CADDY_CROWDSEC_API_KEY}\n    }\n    order crowdsec first"
    )

caddy_blocks.append(
    """    servers {\n        metrics\n    }\n    log {\n        output file /var/log/caddy/caddy_main.log {\n            roll_size 100MiB\n            roll_keep 5\n            roll_keep_for 100d\n        }\n        format json\n        level INFO\n    }\n}\n:2019 {\n    metrics\n}"""
)
caddy_blocks.append(f"{host.data.domain_name} {{\n    respond /_health 200\n}}")


def proxy_block(subdomain, port, name):
    block = f"{subdomain}.{host.data.domain_name} {{\n    reverse_proxy localhost:{port} {{\n        header_up Host {{host}}\n        header_up X-Real-IP {{remote_host}}\n"
    if name == "pocket_id":
        block += "        header_up X-Forwarded-Proto {scheme}\n"
    block += "    }\n"
    if api_key:
        block += "    route {\n        crowdsec\n    }\n"
    block += f"    log {{\n        output file /var/log/caddy/{subdomain}.{host.data.domain_name}.log {{\n            roll_size 100MiB\n            roll_keep 5\n            roll_keep_for 100d\n        }}\n        format json\n        level INFO\n    }}\n}}"
    return block


caddy_blocks.append(proxy_block("pomerium", host.data.pomerium_port, "pomerium"))
caddy_blocks.append(proxy_block(f"cockpit.{host.name}", 9090, "cockpit"))

if "netdata" in svcs:
    caddy_blocks.append(
        proxy_block(
            f"netdata.{host.name}", host.data.get("pomerium_port", 30006), "netdata"
        )
    )
if "syncthing" in svcs:
    caddy_blocks.append(
        proxy_block(
            f"syncthing.{host.name}", host.data.get("pomerium_port", 30006), "syncthing"
        )
    )
if "asf" in svcs:
    caddy_blocks.append(
        proxy_block(f"asf.{host.name}", host.data.get("pomerium_port", 30006), "asf")
    )
if "restic" in svcs:
    caddy_blocks.append(
        proxy_block(
            f"backrest.{host.name}", host.data.get("pomerium_port", 30006), "restic"
        )
    )
if "forgejo" in svcs:
    caddy_blocks.append(proxy_block("git", host.data.forgejo_port, "forgejo"))
if "whoami" in svcs:
    caddy_blocks.append(proxy_block("whoami", host.data.whoami_port, "whoami"))
if "pocket_id" in svcs:
    caddy_blocks.append(proxy_block("id", host.data.pocket_id_port, "pocket_id"))

caddyfile = "{\n" + "\n\n".join(caddy_blocks) + "\n"
caddyfile_changed = files.put(
    name="Template Caddyfile",
    src=io.StringIO(caddyfile),
    dest="/etc/caddy/Caddyfile",
    user="root",
    group="root",
    mode="0644",
).changed

# Secrets
ensure_secret("caddy_crowdsec_api_key", api_key)
bouncer_key = host.data.get("caddy_cs_firewall_bouncer_key", "")
ensure_secret("caddy_cs_firewall_bouncer_key", bouncer_key)

# Caddy Quadlets
deploy_quadlet("caddy-data.volume", "[Volume]")
build_changed = deploy_quadlet(
    "caddy.build",
    "[Unit]\nDescription=Build custom Caddy with CrowdSec bouncer\n[Build]\nImageTag=localhost/caddy-custom:latest\nFile=/etc/caddy/Containerfile\nSetWorkingDirectory=/etc/caddy\nPodmanArgs=--network=host",
)
caddy_cont_changed = deploy_quadlet(
    "caddy.container",
    f"""
[Unit]
Description=Caddy Web Server

[Container]
Image=localhost/caddy-custom:latest
ContainerName=caddy
AutoUpdate=local
{"Secret=caddy_crowdsec_api_key,type=env,target=CADDY_CROWDSEC_API_KEY" if api_key else ""}
Network=host
Volume=/etc/caddy/Caddyfile:/etc/caddy/Caddyfile:ro,z
Volume=caddy-data.volume:/data
Volume=/var/log/caddy:/var/log/caddy:rw,z

NoNewPrivileges=true
DropCapability=all
AddCapability=NET_BIND_SERVICE
AddCapability=DAC_OVERRIDE
AddCapability=FOWNER
AddCapability=CHOWN
ReadOnly=true
Tmpfs=/tmp
Tmpfs=/config

HealthCmd=CMD-SHELL curl -fkLsS -m 2 http://127.0.0.1:2019/metrics > /dev/null || exit 1
HealthInterval=15s
HealthTimeout=5s
HealthRetries=3

[Service]
Restart=always
TimeoutStartSec=900
ExecReload=/usr/bin/podman exec caddy caddy reload --config /etc/caddy/Caddyfile

[Install]
WantedBy=multi-user.target
""",
)

if build_changed or caddy_cont_changed:
    systemd.daemon_reload(name="Reload systemd for caddy")

if cf_changed or build_changed or image_exists != "yes":
    systemd.service(
        name="Rebuild caddy container", service="caddy-build.service", restarted=True
    )

if caddyfile_changed:
    server.shell(
        name="Reload Caddy", commands=["systemctl reload caddy.service || true"]
    )

systemd.service(
    name="Ensure Caddy service is started",
    service="caddy.service",
    running=True,
    restarted=caddy_cont_changed,
)

# CrowdSec Integrations
if api_key:
    files.directory(
        path="/etc/crowdsec-custom/acquis.d", user="root", group="root", mode="0755"
    )
    files.directory(
        path="/etc/crowdsec-custom/parsers", user="root", group="root", mode="0755"
    )

    files.put(
        name="Create caddy.yaml acquis",
        src=io.StringIO(
            "filenames:\n  - /var/log/caddy/*.log\nlabels:\n  type: caddy\n"
        ),
        dest="/etc/crowdsec-custom/acquis.d/caddy.yaml",
        user="root",
        group="root",
        mode="0644",
    )
    files.put(
        name="Whitelist Tailscale network",
        src=io.StringIO(
            "name: ansible-whitelist-tailscale\ndescription: 'Whitelist for Tailscale CGNAT network'\nwhitelist:\n  reason: 'Trusted via Ansible (Tailscale)'\n  cidr:\n    - '100.64.0.0/10'\n"
        ),
        dest="/etc/crowdsec-custom/parsers/ansible-whitelist-tailscale.yaml",
        user="root",
        group="root",
        mode="0644",
    )

    trusted_ips = host.data.get("crowdsec_trusted_ips", [])
    if trusted_ips:
        yaml_ips = "\n".join([f'    - "{ip}"' for ip in trusted_ips])
        files.put(
            name="Whitelist static trusted IPs",
            src=io.StringIO(
                f"name: ansible-whitelist-static\ndescription: 'Whitelist static trusted IPs'\nwhitelist:\n  reason: 'Trusted'\n  ip:\n{yaml_ips}\n"
            ),
            dest="/etc/crowdsec-custom/parsers/ansible-whitelist-static.yaml",
            user="root",
            group="root",
            mode="0644",
        )

    try:
        my_ip = urllib.request.urlopen("https://api.ipify.org").read().decode("utf8")
        files.put(
            name="Whitelist controller IP",
            src=io.StringIO(
                f"name: ansible-whitelist-controller\nwhitelist:\n  reason: 'Trusted Controller'\n  ip:\n    - \"{my_ip}\"\n"
            ),
            dest="/etc/crowdsec-custom/parsers/ansible-whitelist-controller.yaml",
            user="root",
            group="root",
            mode="0644",
        )
    except Exception:
        pass

    deploy_quadlet("crowdsec-data.volume", "[Volume]")
    deploy_quadlet("crowdsec-config.volume", "[Volume]")
    cs_changed = deploy_quadlet(
        "crowdsec.container",
        """
[Unit]
Description=CrowdSec IDS Container
After=network-online.target

[Container]
Image=docker.io/crowdsecurity/crowdsec:latest
ContainerName=crowdsec
AutoUpdate=registry
Network=host
Secret=caddy_crowdsec_api_key,type=env,target=BOUNCER_KEY_caddy
Environment=COLLECTIONS=crowdsecurity/caddy
Volume=crowdsec-data.volume:/var/lib/crowdsec/data
Volume=crowdsec-config.volume:/etc/crowdsec
Volume=/var/log/caddy:/var/log/caddy:ro,z
Volume=/etc/crowdsec-custom/acquis.d/caddy.yaml:/etc/crowdsec/acquis.d/caddy.yaml:ro,z
Volume=/etc/crowdsec-custom/parsers:/etc/crowdsec/parsers/s02-enrich/ansible:ro,z

HealthCmd=cscli lapi status
HealthInterval=5s
HealthTimeout=5s
HealthRetries=5
Notify=healthy

[Service]
Restart=always
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
    )

    systemd.service(
        name="Ensure CrowdSec service is started",
        service="crowdsec.service",
        running=True,
        restarted=cs_changed,
        daemon_reload=cs_changed,
    )

if api_key and bouncer_key:
    files.directory(path="/etc/crowdsec", user="root", group="root", mode="0755")
    bouncer_conf = "mode: ${BACKEND}\npid_dir: /var/run/\nupdate_frequency: 10s\ndaemonize: false\nlog_mode: stdout\nlog_level: info\napi_url: ${API_URL}\napi_key: ${API_KEY}\ndisable_ipv6: ${DISABLE_IPV6}\nnftables:\n  ipv4:\n    enabled: true\n    set-only: false\n    table: crowdsec\n    chain: crowdsec-chain\n  ipv6:\n    enabled: true\n    set-only: false\n    table: crowdsec6\n    chain: crowdsec6-chain\n"
    files.put(
        name="Create Firewall Bouncer config",
        src=io.StringIO(bouncer_conf),
        dest="/etc/crowdsec/crowdsec-firewall-bouncer.yaml",
        user="root",
        group="root",
        mode="0644",
    )

    fw_changed = deploy_quadlet(
        "cs-firewall.container",
        """
[Unit]
Description=CrowdSec Firewall Bouncer
After=crowdsec.service network-online.target
Requires=crowdsec.service

[Container]
Image=ghcr.io/shgew/cs-firewall-bouncer-docker:latest
ContainerName=cs-firewall-bouncer
AutoUpdate=registry
Network=host
AddCapability=NET_ADMIN
AddCapability=NET_RAW
Environment=API_URL=http://127.0.0.1:8080
Secret=caddy_cs_firewall_bouncer_key,type=env,target=API_KEY
Environment=BACKEND=nftables
Environment=DISABLE_IPV6=false
Volume=/etc/crowdsec/crowdsec-firewall-bouncer.yaml:/config/crowdsec-firewall-bouncer.yaml:ro,z

[Service]
Restart=always
RestartSec=5
TimeoutStartSec=900

[Install]
WantedBy=multi-user.target
""",
    )

    systemd.service(
        name="Ensure Firewall Bouncer is started",
        service="cs-firewall.service",
        running=True,
        restarted=fw_changed,
        daemon_reload=fw_changed,
    )
