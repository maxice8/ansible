#!/usr/bin/env python3
"""Enroll Mashu when needed and reconcile its Tailscale preferences."""

import json
import os
import subprocess
import sys
import tempfile

FLAGS = [
    "--ssh=true",
    "--accept-routes=true",
    "--accept-dns=true",
    "--advertise-tags=tag:server",
]
PREFERENCES = {
    "RunSSH": True,
    "RouteAll": True,
    "CorpDNS": True,
    "AdvertiseTags": ["tag:server"],
}


def read_json(*args):
    result = subprocess.run(
        ["tailscale", *args], capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def configure(check=False):
    status = read_json("status", "--json")
    state = status.get("BackendState")
    if check:
        if state != "Running":
            return 1
        prefs = read_json("debug", "prefs")
        return int(any(prefs.get(key) != value for key, value in PREFERENCES.items()))

    # Never force reauthentication of a registered device or restart a login
    # that is awaiting device approval.
    if state in {"NeedsLogin", "NoState"}:
        auth_key = os.environ.pop("TS_AUTHKEY", "").strip()
        if not auth_key:
            raise RuntimeError("Set TS_AUTHKEY for initial Tailscale enrollment")
        # /run is volatile; NamedTemporaryFile is mode 0600 and removes the key
        # on success or failure. The CLI receives only the file path.
        # The Nix oneshot has a private writable runtime directory under ProtectSystem.
        with tempfile.NamedTemporaryFile(
            mode="w", dir=os.environ.get("RUNTIME_DIRECTORY", "/run")
        ) as key_file:
            key_file.write(auth_key)
            key_file.flush()
            subprocess.run(
                [
                    "tailscale",
                    "up",
                    f"--auth-key=file:{key_file.name}",
                    "--timeout=60s",
                    *FLAGS,
                ],
                check=True,
                capture_output=True,
            )
    elif state in {"Running", "Stopped"}:
        # Tags belong to `up`; `set` supports only the other mutable preferences.
        set_flags = [flag for flag in FLAGS if not flag.startswith("--advertise-tags=")]
        subprocess.run(
            ["tailscale", "set", *set_flags], check=True, capture_output=True
        )
        if (
            read_json("debug", "prefs").get("AdvertiseTags")
            != PREFERENCES["AdvertiseTags"]
        ):
            subprocess.run(
                ["tailscale", "up", "--timeout=60s", *FLAGS],
                check=True,
                capture_output=True,
            )
        elif state == "Stopped":
            subprocess.run(
                ["tailscale", "up", "--timeout=60s"],
                check=True,
                capture_output=True,
            )
    else:
        raise RuntimeError(
            f"Tailscale is {state}; resolve daemon/device approval first"
        )
    if configure(check=True):
        raise RuntimeError("Tailscale enrollment/preferences did not converge")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(configure(check=sys.argv[1:] == ["--check"]))
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as error:
        # Do not print subprocess output: authentication responses can contain
        # credentials or login URLs. Keep the failure visible without them.
        print(f"Tailscale configuration failed: {error}", file=sys.stderr)
        sys.exit(1)
