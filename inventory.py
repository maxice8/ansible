plain_group_vars = {
    "domain_name": "maxice8.com",
}

# Define your hosts and their specific data
servers = [
    (
        "ryuu",
        {
            "ssh_user": "core",
            "host_services": [
                "pocket_id",
                "forgejo",
                "forgejo_runner",
                "whoami",
                "syncthing",
                "netdata",
                "asf",
                "pomerium",
                "pingvin_share",
                "netbird_server",
                "restic",
                "caddy",
            ],
            "forgejo_ssh_port": 30022,
            "asf_port": 30004,
            "backrest_port": 30005,
            "pomerium_port": 30006,
        },
    ),
]
