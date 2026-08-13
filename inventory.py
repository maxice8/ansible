servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "795a3a972224da6a7f9d32c3e946445f062b60fb46028476715affeb688236e3",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.1",
            },
            "k3s": {
                "installer_sha256": "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad",
                "version": "v1.36.3+k3s1",
            },
            # Access
            "ssh_user": "ubuntu",
        },
    ),
]
