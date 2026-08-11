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
            # Access
            "ssh_hostname": "167.126.15.226",
            "ssh_public_key": "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBGGnv3RrnwshBYkxF88Z1Rd+OiQGG8esijpkL1RhLWH/fhMuFHQuUtv+qx9D5qcv722Yla12KcbGoefm2OxlQZc= max",
            "ssh_user": "ubuntu",
        },
    ),
]
