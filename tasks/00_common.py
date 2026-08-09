from pyinfra import host
from pyinfra.operations import files, server

for directory in ["/etc/containers/systemd", "/etc/sysusers.d", "/etc/tmpfiles.d"]:
    files.directory(
        name=f"Ensure {directory} exists",
        path=directory,
        user="root",
        group="root",
        mode="0755",
    )

if host.data.get("ssh_pub_key"):
    server.user_authorized_keys(
        name="Ensure admin SSH key is authorized for the configured user",
        public_keys=[host.data.get("ssh_pub_key")],
        user=host.data.get("ssh_user"),
    )
