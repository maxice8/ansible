import os

from pyinfra import host, local
from pyinfra.operations import server

only_tasks_env = os.environ.get("TASKS")
targeted_tasks = (
    [task.strip() for task in only_tasks_env.split(",")] if only_tasks_env else None
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

for task in (
    "user",
    "ssh",
    "netbird",
    "kernel",
    "services",
    "firewall",
    "k3s",
    "argocd",
):
    if should_run(task_name=task):
        local.include(f"tasks/{task}.py")
