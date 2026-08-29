servers = [
    (
        "mashu",
        {
            # Managed software
            "argocd": {
                "manifest_sha256": "9a87f2b3e14c278f12501eb0ef5c3955b27cf05370ca425381c6a908cf85a5c5",
                "repository_url": "https://github.com/maxice8/ansible.git",
                "version": "v3.5.2",
            },
            "k3s": {
                "installer_sha256": "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad",
                "version": "v1.36.4+k3s1",
            },
            # Access
            "ssh_user": "ubuntu",
        },
    ),
]
