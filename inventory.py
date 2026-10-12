servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "90dc9094bf4c5964afd9c0e35d735e1c2fcbbda4f8e36799c092d9864ed65f50",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.5",
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
