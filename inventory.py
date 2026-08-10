plain_group_vars = {
    "argocd_repository_url": "https://github.com/maxice8/ansible.git",
    "domain_name": "maxice8.com",
    "k3s_version": "v1.35.5+k3s1",
    "ssh_public_key": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBGGnv3RrnwshBYkxF88Z1Rd+OiQGG8esijpkL1RhLWH/fhMuFHQuUtv+qx9D5qcv722Yla12KcbGoefm2OxlQZc= max",
}

servers = (
    [
        (
            "mashu",
            {
                "netbird_ipv4": "100.119.192.118",
                "private_ipv4": "10.0.0.112",
                "ssh_hostname": "167.126.15.226",
                "ssh_user": "ubuntu",
            },
        ),
    ],
    plain_group_vars,
)
