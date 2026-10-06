servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "1feb02cc7bacf3a379da58b0ca8c6f07d18288cd04d531dabd08816375e5e010",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.4",
            },
            "k3s": {
                "installer_sha256": "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad",
                "version": "v1.36.4+k3s1",
            },
            # Access
            "ssh_hostname": "2603:c025:4005:8f7e:0:b837:618:268c",
            "ssh_user": "ubuntu",
        },
    ),
]
