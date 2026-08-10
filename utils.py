import hashlib
import io
import shlex

from pyinfra import host
from pyinfra.api import FactBase
from pyinfra.operations import files, server


class ShellFact(FactBase):
    def command(self, cmd):
        return cmd

    def process(self, output):
        return output[0] if output else ""


def ensure_secret(secret_name: str, secret_value: str) -> bool:
    """Create or replace a Podman secret when its configured value changes."""
    if not secret_value:
        return False

    secret_hash = hashlib.sha256(secret_value.encode()).hexdigest()
    hash_label = "io.maxice8.content-sha256"
    current_hash = host.get_fact(
        ShellFact,
        "podman secret inspect "
        f"--format '{{{{ index .Spec.Labels \"{hash_label}\" }}}}' "
        f"{shlex.quote(secret_name)} 2>/dev/null || true",
    )

    if current_hash != secret_hash:
        server.shell(
            name=f"Store {secret_name} as Podman secret",
            commands=[
                (
                    "head -c -1 | podman secret create --replace "
                    f"--label {hash_label}={secret_hash} {shlex.quote(secret_name)} -"
                )
            ],
            _stdin=secret_value,
        )
        return True

    return False


def deploy_quadlet(filename: str, content: str) -> bool:
    """Deploys a Quadlet file to /etc/containers/systemd and returns True if changed."""
    return files.put(
        name=f"Deploy {filename}",
        src=io.StringIO(content.strip() + "\n"),
        dest=f"/etc/containers/systemd/{filename}",
        user="root",
        group="root",
        mode="0600",
    ).changed


def deploy_template(
    *,
    name: str,
    src: str,
    dest: str,
    user: str = "root",
    group: str = "root",
    mode: str = "0644",
    **data: object,
) -> bool:
    """Render a local Jinja template and deploy the result."""
    return files.template(
        name=name,
        src=src,
        dest=dest,
        user=user,
        group=group,
        mode=mode,
        jinja_env_kwargs={
            "lstrip_blocks": True,
            "trim_blocks": True,
        },
        **data,
    ).changed


def apply_sysusers(name: str, content: str) -> bool:
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


def apply_tmpfiles(name: str, content: str) -> bool:
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
