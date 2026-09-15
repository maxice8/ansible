import io
import re

from pyinfra import host
from pyinfra.facts.server import Command
from pyinfra.operations import files, server


def get_public_interface():
    interface = host.get_fact(
        Command,
        command=(
            "ip -o -4 route show default | "
            "awk 'NR == 1 {for (i = 1; i <= NF; i++) "
            'if ($i == "dev") {print $(i + 1); exit}}\''
        ),
    )
    if not interface or not re.fullmatch(r"[A-Za-z0-9_.:@-]+", interface):
        raise RuntimeError("Cannot discover the public network interface")
    return interface


def apply_manifest(name, filename, contents, after=()):
    path = f"/usr/local/src/{filename}.yaml"
    changed = files.put(
        name=f"Configure {name}",
        src=io.StringIO(contents),
        dest=path,
        user="root",
        group="root",
        mode="0644",
    ).changed
    state = host.get_fact(
        Command,
        command=(
            f"k3s kubectl diff -f {path} >/dev/null 2>&1; "
            "case $? in 0) printf current;; *) printf drifted;; esac"
        ),
    )
    if changed or state != "current":
        server.shell(
            name=f"Apply {name}",
            commands=[f"k3s kubectl apply -f {path}", *after],
        )
