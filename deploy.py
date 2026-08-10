import os
import subprocess

from pyinfra import host, local

from inventory import plain_group_vars


def load_sops_vars(filepath: str) -> dict:
    if not os.path.exists(filepath):
        return {}

    env = os.environ.copy()
    env["SOPS_AGE_KEY_FILE"] = os.path.abspath(".age-key.txt")

    try:
        result = subprocess.run(
            ["sops", "-d", filepath],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse standard ENV key=value pairs natively in Python
        vars_dict = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip().lower()  # Convert CROWDSEC to crowdsec
                val = val.strip().strip('"').strip("'")

                # Reconstruct lists from comma-separated strings
                if key == "crowdsec_trusted_ips" and val:
                    vars_dict[key] = [ip.strip() for ip in val.split(",")]
                else:
                    vars_dict[key] = val

        return vars_dict

    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        raise


sops_host_vars = load_sops_vars(f"host_vars/{host.name}.sops.env")
sops_group_vars = load_sops_vars("group_vars/servers.sops.env")

all_vars = {**plain_group_vars, **sops_group_vars, **sops_host_vars}

# Merge them into pyinfra's host.data object
for key, value in all_vars.items():
    setattr(host.data, key, value)

host_services = host.data.host_services
pomerium_dependents = ("cockpit", "netdata")
configured_pomerium_dependents = [
    service for service in pomerium_dependents if service in host_services
]

# Cockpit and Netdata use the private Pomerium network.
# Run these services after Pomerium creates the network.
if configured_pomerium_dependents and "pomerium" not in host_services:
    dependent_names = ", ".join(configured_pomerium_dependents)
    raise ValueError(f"The following services require Pomerium: {dependent_names}")

if "pomerium" in host_services:
    pomerium_index = host_services.index("pomerium")
    incorrectly_ordered_dependents = [
        service
        for service in configured_pomerium_dependents
        if host_services.index(service) < pomerium_index
    ]
    if incorrectly_ordered_dependents:
        dependent_names = ", ".join(incorrectly_ordered_dependents)
        raise ValueError(f"These services must run after Pomerium: {dependent_names}")

only_tasks_env = os.environ.get("TASKS")
targeted_tasks = (
    [t.strip() for t in only_tasks_env.split(",")] if only_tasks_env else None
)


def should_run(task_name: str) -> bool:
    if targeted_tasks is None:
        return True
    return task_name in targeted_tasks


# Common host state is a prerequisite for every deployment, including filtered runs.
local.include("tasks/00_common.py")

if should_run("netbird"):
    local.include("tasks/netbird.py")

if should_run("podman"):
    local.include("tasks/podman.py")

for service in host_services:
    if should_run(service):
        local.include(f"tasks/{service}.py")
