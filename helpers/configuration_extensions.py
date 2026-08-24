"""Register configuration extensions for activation by their finalizer."""

import re
from collections.abc import Callable
from pathlib import Path

from pyinfra import host
from pyinfra.operations import files

REGISTRY_DATA_KEY = "managed_configuration_extensions"
_VALID_EXTENSION_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def sync_configuration_extension(
    name: str,
    *,
    after_refresh: Callable[[], None] | None = None,
) -> bool:
    """Synchronize a confext and register its post-refresh action."""
    if not _VALID_EXTENSION_NAME.fullmatch(name):
        raise ValueError(f"Invalid configuration extension name: {name!r}")

    source = _REPOSITORY_ROOT / "configuration-extensions" / name
    release_file = source / "etc" / "extension-release.d" / f"extension-release.{name}"
    if not release_file.is_file():
        raise ValueError(
            f"Configuration extension {name!r} is missing "
            f"{release_file.relative_to(source)}"
        )

    registry = host.data.get(REGISTRY_DATA_KEY, {})
    if name in registry:
        raise ValueError(f"Configuration extension {name!r} was registered twice")

    changed = files.sync(
        name=f"Synchronize the {name} configuration extension",
        src=str(source),
        dest=f"/var/lib/confexts/{name}",
        user="root",
        group="root",
        mode="0644",
        dir_mode="0755",
        delete=True,
    ).changed

    registry[name] = {
        "changed": changed,
        "after_refresh": after_refresh,
    }
    # Host data values are copied when read, so persist the updated registry.
    setattr(host.data, REGISTRY_DATA_KEY, registry)

    return changed
