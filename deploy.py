import os

from pyinfra import host, local
from pyinfra.operations import server

# This decides run order
OWNER_TASKS = (
    "user",
    "ssh",
    "netbird",
    "kernel",
    "services",
    "unattended_upgrades",
    "usg",
    "firewall",
    "k3s",
    "argocd",
)
EXTENSION_FINALIZERS = (
    ("system-extensions", "managed_system_extensions"),
    ("configuration-extensions", "managed_configuration_extensions"),
)
AVAILABLE_TASKS = OWNER_TASKS + tuple(task for task, _ in EXTENSION_FINALIZERS)

only_tasks_env = os.environ.get("TASKS")
targeted_tasks = (
    {task.strip() for task in only_tasks_env.split(",") if task.strip()}
    if only_tasks_env
    else None
)

if targeted_tasks is not None:
    unknown_tasks = targeted_tasks.difference(AVAILABLE_TASKS)
    if unknown_tasks:
        raise ValueError(
            f"Unknown TASKS: {', '.join(sorted(unknown_tasks))}. "
            f"Available tasks: {', '.join(AVAILABLE_TASKS)}"
        )


def should_run(task_name: str) -> bool:
    """Return true when the task is part of this deployment."""
    # Disable 'usg' for mashu host as it is on Ubuntu 26.04 which
    # is not yet supported
    if task_name == "usg" and host.name == "mashu":
        return False
    if targeted_tasks is None:
        return True
    return task_name in targeted_tasks


server.hostname(
    name="Set the Mashu host name",
    hostname=host.name,
)

for task in OWNER_TASKS:
    if should_run(task_name=task):
        local.include(f"tasks/{task}.py")

# Extension-owning tasks register their payloads while they are included. Run
# each relevant finalizer once, including during a targeted deployment.
for finalizer, registry_key in EXTENSION_FINALIZERS:
    if should_run(finalizer) or host.data.get(registry_key):
        local.include(f"tasks/{finalizer}.py")
