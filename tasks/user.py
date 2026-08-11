from pyinfra import host
from pyinfra.operations import server

SSH_PUBLIC_KEY = (
    "ecdsa-sha2-nistp256 "
    "AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBGGnv3RrnwshBYkxF88Z1Rd+OiQGG8esijpkL1RhLWH/fhMuFHQuUtv+qx9D5qcv722Yla12KcbGoefm2OxlQZc= "
    "max"
)

server.user_authorized_keys(
    name="Authorize the administrator SSH key",
    user=host.data.ssh_user,
    public_keys=[SSH_PUBLIC_KEY],
    delete_keys=True,
)
