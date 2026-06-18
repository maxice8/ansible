# inventory.py
plain_group_vars = {
    "tailnet_name": "neko-great",
    "domain_name": "maxice8.com",
}

# Define your hosts and their specific data
servers = [
    (
        "mika",
        {
            "host_services": ["keep_vm_alive"],
            "group_services": [],
        },
    ),
    (
        "ryuu",
        {
            "ssh_user": "core",  # Replaces ansible_user: core
            "host_services": [
                "caddy",
                "pocket_id",
                "forgejo",
                "forgejo_runner",
                "whoami",
                "syncthing",
                "netdata",
                "asf",
                "pomerium",
            ],
            "group_services": ["restic"],
            "whoami_port": 30001,
            "forgejo_port": 30002,
            "forgejo_ssh_port": 30022,
            "pocket_id_port": 30003,
            "asf_port": 30004,
            "backrest_port": 30005,
            "pomerium_port": 30006,
        },
    ),
]
