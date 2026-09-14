servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "7efe2d6bbc03f63623640f1e4198f16c84009d510fb810ef71e56df1b7614ba9",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.3",
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
