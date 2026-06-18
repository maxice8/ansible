from pyinfra.operations import files

for directory in ["/etc/containers/systemd", "/etc/sysusers.d", "/etc/tmpfiles.d"]:
    files.directory(
        name=f"Ensure {directory} exists",
        path=directory,
        user="root", group="root", mode="0755",
    )
