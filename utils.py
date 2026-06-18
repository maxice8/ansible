# utils.py
import io
from pyinfra import host
from pyinfra.api import FactBase
from pyinfra.operations import server, files


class ShellFact(FactBase):
    def command(self, cmd):
        return cmd

    def process(self, output):
        return output[0] if output else ""


def ensure_secret(secret_name, secret_value):
    """Idempotently creates a podman secret if it doesn't exist."""
    if not secret_value:
        return False
    exists = host.get_fact(
        ShellFact, f"podman secret exists {secret_name} && echo 'yes' || echo 'no'"
    )
    if exists != "yes":
        server.shell(
            name=f"Store {secret_name} as Podman Secret",
            commands=[
                f"echo -n '{secret_value}' | podman secret create {secret_name} -"
            ],
        )
        return True
    return False


def deploy_quadlet(filename, content):
    """Deploys a Quadlet file to /etc/containers/systemd and returns True if changed."""
    return files.put(
        name=f"Deploy {filename}",
        src=io.StringIO(content.strip() + "\n"),
        dest=f"/etc/containers/systemd/{filename}",
        user="root",
        group="root",
        mode="0600",
    ).changed


def apply_sysusers(name, content):
    """Deploys and immediately applies a sysusers config."""
    changed = files.put(
        name=f"Create {name} sysusers",
        src=io.StringIO(content.strip() + "\n"),
        dest=f"/etc/sysusers.d/{name}.conf",
        user="root",
        group="root",
        mode="0644",
    ).changed
    if changed:
        server.shell(
            name=f"Apply {name} sysusers",
            commands=[f"systemd-sysusers /etc/sysusers.d/{name}.conf"],
        )
    return changed


def apply_tmpfiles(name, content):
    """Deploys and immediately applies a tmpfiles config."""
    changed = files.put(
        name=f"Create {name} tmpfiles",
        src=io.StringIO(content.strip() + "\n"),
        dest=f"/etc/tmpfiles.d/{name}.conf",
        user="root",
        group="root",
        mode="0644",
    ).changed
    if changed:
        server.shell(
            name=f"Apply {name} tmpfiles",
            commands=[f"systemd-tmpfiles --create /etc/tmpfiles.d/{name}.conf"],
        )
    return changed
