import os
import subprocess

import yaml
from pyinfra import host, local

from inventory import plain_group_vars


def load_sops_vars(filepath):
    # If the file doesn't exist (e.g., no host vars for this specific host), return empty
    if not os.path.exists(filepath):
        return {}

    # Explicitly tell SOPS where to find the age key
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
        return yaml.safe_load(result.stdout) or {}
    except subprocess.CalledProcessError as e:
        # Don't swallow the error silently! Print SOPS's actual stderr output
        print(f"SOPS Decryption failed for {filepath}:\n{e.stderr}")
        raise
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        raise


# 1. Load Secrets & Vars into the host dynamically
sops_host_vars = load_sops_vars(f"host_vars/{host.name}.sops.yaml")
sops_group_vars = load_sops_vars("group_vars/servers.sops.yaml")

all_vars = {**plain_group_vars, **sops_group_vars, **sops_host_vars}

# Merge them into pyinfra's host.data object
for key, value in all_vars.items():
    setattr(host.data, key, value)

# 2. Determine services to configure
host_services = host.data.get("host_services", [])
group_services = host.data.get("group_services", [])
configured_services = host_services + group_services

setattr(host.data, "configured_services", configured_services)

# 3. Base Setup
local.include("tasks/00_common.py")
local.include("tasks/tailscale.py")
local.include("tasks/podman.py")
local.include("tasks/cockpit.py")

# 4. Service Loop
for service in configured_services:
    # Dynamically include the task script for each service
    local.include(f"tasks/{service}.py")
