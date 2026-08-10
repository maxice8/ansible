plain_group_vars = {
    "domain_name": "maxice8.com",
    "k3s_installer_sha256": "8598e002e61d658fed7b7542fc6d2c66d8da6eae69e088830105d2ee1ffb6d91",
    "k3s_installer_url": "https://raw.githubusercontent.com/k3s-io/k3s/v1.35.5%2Bk3s1/install.sh",
    "k3s_version": "v1.35.5+k3s1",
    "ssh_public_key": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBGGnv3RrnwshBYkxF88Z1Rd+OiQGG8esijpkL1RhLWH/fhMuFHQuUtv+qx9D5qcv722Yla12KcbGoefm2OxlQZc= max",
}

servers = (
    [
        (
            "mashu",
            {
                "netbird_ipv4": "100.119.192.118",
                "ssh_hostname": "167.126.15.226",
                "ssh_user": "ubuntu",
            },
        ),
    ],
    plain_group_vars,
)
