import io

from pyinfra import host
from pyinfra.operations import files, server, systemd

ssh_config_changed = files.put(
    name="Deploy the Mashu SSH policy",
    src=io.StringIO(
        f"""AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
PermitRootLogin no
AllowUsers {host.data.ssh_user}
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding local
PermitTunnel no
MaxAuthTries 3
LoginGraceTime 30
"""
    ),
    dest="/etc/ssh/sshd_config.d/10-homelab.conf",
    user="root",
    group="root",
    mode="0600",
).changed

if ssh_config_changed:
    server.shell(
        name="Validate the Mashu SSH policy",
        commands=["sshd -t"],
    )

systemd.service(
    name="Reload SSH after a policy change",
    service="ssh.service",
    running=True,
    enabled=True,
    reloaded=ssh_config_changed,
)
