servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "a32bf36a437071a1f563ebf9e81c8a39fba9057c17db7d5d041afb7b6e3f4afe",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.0",
            },
            "k3s": {
                "installer_sha256": "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad",
                "version": "v1.36.3+k3s1",
            },
            "netbird": {
                "version": "0.76.3",
            },
            # Network
            "netbird_ipv4": "100.119.192.118",
            "private_ipv4": "10.0.0.112",
            "public_ipv4": "167.126.15.226",
            "public_ipv6": "2603:c025:4005:8f7e:0:b837:618:268c",
            # Access
            "ssh_hostname": "167.126.15.226",
            "ssh_public_key": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBGGnv3RrnwshBYkxF88Z1Rd+OiQGG8esijpkL1RhLWH/fhMuFHQuUtv+qx9D5qcv722Yla12KcbGoefm2OxlQZc= max",
            "ssh_user": "ubuntu",
        },
    ),
]
