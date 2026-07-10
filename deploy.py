import os
import subprocess

from pyinfra import host, local

from inventory import plain_group_vars


def load_sops_vars(filepath):
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


# Make sure to update the file extensions being loaded here!
sops_host_vars = load_sops_vars(f"host_vars/{host.name}.sops.env")
sops_group_vars = load_sops_vars("group_vars/servers.sops.env")

all_vars = {**plain_group_vars, **sops_group_vars, **sops_host_vars}

# Merge them into pyinfra's host.data object
for key, value in all_vars.items():
    setattr(host.data, key, value)

# 2. Determine services to configure
host_services = host.data.get("host_services", [])
group_services = host.data.get("group_services", [])
configured_services = host_services + group_services

setattr(host.data, "configured_services", configured_services)

# 3. Execution Filtering Logic
# Grabs a comma-separated list from the terminal, e.g., TASKS=podman,pingvin_share
only_tasks_env = os.environ.get("TASKS")
targeted_tasks = (
    [t.strip() for t in only_tasks_env.split(",")] if only_tasks_env else None
)


def should_run(task_name):
    # If no limit is provided, run everything as normal
    if targeted_tasks is None:
        return True
    return task_name in targeted_tasks


# 00_common setup should almost always run to ensure folder structures exist,
# but we respect the filter if explicitly targeted.
if should_run("00_common") or targeted_tasks:
    local.include("tasks/00_common.py")

if should_run("tailscale"):
    local.include("tasks/tailscale.py")

if should_run("podman"):
    local.include("tasks/podman.py")

if should_run("cockpit"):
    local.include("tasks/cockpit.py")

# 4. Service Loop
for service in configured_services:
    if should_run(service):
        local.include(f"tasks/{service}.py")
