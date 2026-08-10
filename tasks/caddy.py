import io
import urllib.request

from pyinfra import host
from pyinfra.operations import files, systemd

from utils import (
    ShellFact,
    apply_tmpfiles,
    deploy_quadlet,
    deploy_template,
    ensure_secret,
)

apply_tmpfiles(
    "caddy",
    """d /etc/caddy 0755 root root -
d /var/log/caddy 0755 root root -""",
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
svcs = host.data.host_services
pomerium_upstream = "pomerium:30006"
caddyfile_changed = deploy_template(
    name="Template Caddyfile",
    src="templates/caddy/Caddyfile.j2",
    dest="/etc/caddy/Caddyfile",
    user="root",
    group="root",
    mode="0644",
    crowdsec_enabled=bool(api_key),
    domain=host.data.domain_name,
    hostname=host.name,
    pomerium_upstream=pomerium_upstream,
    services=svcs,
)

# Secrets
api_secret_changed = ensure_secret("caddy_crowdsec_api_key", api_key)
bouncer_key = host.data.get("caddy_cs_firewall_bouncer_key", "")
bouncer_secret_changed = ensure_secret("caddy_cs_firewall_bouncer_key", bouncer_key)

# Caddy Quadlets
crowdsec_network_changed = False
if api_key:
    crowdsec_network_changed = deploy_quadlet(
        "crowdsec.network",
        """[Unit]
Description=Isolated Dual-Stack Network for CrowdSec

[Network]
IPv6=True""",
    )

deploy_quadlet("caddy-data.volume", "[Volume]")
build_changed = deploy_quadlet(
    "caddy.build",
    """[Unit]
Description=Build custom Caddy with CrowdSec bouncer

[Build]
ImageTag=localhost/caddy-custom:latest
File=/etc/caddy/Containerfile
SetWorkingDirectory=/etc/caddy
PodmanArgs=--network=host""",
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
Network=pomerium.network
{"Network=crowdsec.network" if api_key else ""}
{"Network=forgejo.network" if "forgejo" in svcs else ""}
{"Network=whoami.network" if "whoami" in svcs else ""}
{"Network=pocket-id.network" if "pocket_id" in svcs else ""}
{"Network=pingvin-share.network" if "pingvin_share" in svcs else ""}
{"Network=netbird-server.network" if "netbird_server" in svcs else ""}
PublishPort=80:80
PublishPort=443:443
PublishPort=443:443/udp
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

if build_changed or caddy_cont_changed or crowdsec_network_changed:
    systemd.daemon_reload(name="Reload systemd for caddy")

if cf_changed or build_changed or image_exists != "yes":
    systemd.service(
        name="Rebuild caddy container", service="caddy-build.service", restarted=True
    )

systemd.service(
    name="Ensure Caddy service is started",
    service="caddy.service",
    running=True,
    restarted=(
        caddy_cont_changed
        or caddyfile_changed
        or api_secret_changed
        or crowdsec_network_changed
    ),
)

# CrowdSec Integrations
if api_key:
    files.directory(
        path="/etc/crowdsec-custom/acquis.d", user="root", group="root", mode="0755"
    )
    files.directory(
        path="/etc/crowdsec-custom/parsers", user="root", group="root", mode="0755"
    )

    wl_netbird_changed = deploy_template(
        name="Whitelist NetBird network",
        src="templates/crowdsec/whitelist.yaml.j2",
        dest="/etc/crowdsec-custom/parsers/ansible-whitelist-netbird.yaml",
        user="root",
        group="root",
        mode="0644",
        description="Whitelist for NetBird networks",
        whitelist_name="ansible-whitelist-netbird",
        reason="Trusted via Ansible (NetBird)",
        values=["100.64.0.0/10", "fdcb:d175:272d:bff5::/64"],
        value_type="cidr",
    )

    trusted_ips = host.data.get("crowdsec_trusted_ips", [])
    wl_static_changed = False
    if trusted_ips:
        wl_static_changed = deploy_template(
            name="Whitelist static trusted IPs",
            src="templates/crowdsec/whitelist.yaml.j2",
            dest="/etc/crowdsec-custom/parsers/ansible-whitelist-static.yaml",
            user="root",
            group="root",
            mode="0644",
            description="Whitelist static trusted IPs",
            whitelist_name="ansible-whitelist-static",
            reason="Trusted",
            values=trusted_ips,
            value_type="ip",
        )

    wl_controller_changed = False
    try:
        my_ip = (
            urllib.request.urlopen("https://api.ipify.org", timeout=5)
            .read()
            .decode("utf8")
        )
        wl_controller_changed = deploy_template(
            name="Whitelist controller IP",
            src="templates/crowdsec/whitelist.yaml.j2",
            dest="/etc/crowdsec-custom/parsers/ansible-whitelist-controller.yaml",
            user="root",
            group="root",
            mode="0644",
            description="Trusted Controller IP",
            whitelist_name="ansible-whitelist-controller",
            reason="Trusted Controller",
            values=[my_ip],
            value_type="ip",
        )
    except urllib.error.HTTPError as e:
        host.noop(f"Failed to fetch controller IP for whitelisting: {e}")
    except urllib.error.URLError as e:
        host.noop(f"Failed to fetch controller IP for whitelisting: {e}")

    # Track overall whitelist file state changes
    whitelists_changed = (
        wl_netbird_changed or wl_static_changed or wl_controller_changed
    )

    files.put(
        name="Create caddy.yaml acquis",
        src=io.StringIO(
            """filenames:
  - /var/log/caddy/*.log
labels:
  type: caddy
"""
        ),
        dest="/etc/crowdsec-custom/acquis.d/caddy.yaml",
        user="root",
        group="root",
        mode="0644",
    )

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
Network=crowdsec.network
PublishPort=127.0.0.1:8080:8080
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
        restarted=cs_changed or whitelists_changed or api_secret_changed,
        daemon_reload=cs_changed,
    )

if api_key and bouncer_key:
    files.directory(path="/etc/crowdsec", user="root", group="root", mode="0755")
    files.put(
        name="Create Firewall Bouncer config",
        src=io.StringIO(
            """mode: ${BACKEND}
pid_dir: /var/run/
update_frequency: 10s
daemonize: false
log_mode: stdout
log_level: info
api_url: ${API_URL}
api_key: ${API_KEY}
disable_ipv6: ${DISABLE_IPV6}
nftables:
  ipv4:
    enabled: true
    set-only: false
    table: crowdsec
    chain: crowdsec-chain
  ipv6:
    enabled: true
    set-only: false
    table: crowdsec6
    chain: crowdsec6-chain
"""
        ),
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
        restarted=fw_changed or bouncer_secret_changed,
        daemon_reload=fw_changed,
    )
