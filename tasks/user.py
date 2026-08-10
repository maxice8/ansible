from pyinfra import host
from pyinfra.operations import server

server.user_authorized_keys(
    name="Authorize the administrator SSH key",
    user=host.data.ssh_user,
    public_keys=[host.data.ssh_public_key],
    delete_keys=True,
)
