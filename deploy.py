import os

from pyinfra import host, local
from pyinfra.operations import server

AVAILABLE_TASKS = (
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
    if targeted_tasks is None:
        return True
    return task_name in targeted_tasks


server.hostname(
    name="Set the Mashu host name",
    hostname=host.name,
)

for task in AVAILABLE_TASKS:
    if should_run(task_name=task):
        local.include(f"tasks/{task}.py")
