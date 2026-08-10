plain_group_vars = {
    "domain_name": "maxice8.com",
}

# Use a fixed subnet for the private Pomerium network.
# Host services bind to the gateway of this subnet.
POMERIUM_HOST_IPV4_SUBNET = "172.31.255.0/24"
POMERIUM_HOST_IPV4_GATEWAY = "172.31.255.1"

# Define your hosts and their specific data
servers = [
    (
        "ryuu",
        {
            "ssh_user": "core",
            # List services in deployment order.
            "host_services": [
                "pocket_id",
                "forgejo",
                "forgejo_runner",
                "whoami",
                "syncthing",
                "asf",
                "pingvin_share",
                "netbird_server",
                "restic",
                "pomerium",
                "cockpit",
                "netdata",
                "caddy",
            ],
        },
    ),
]
