#!/usr/bin/env python3
"""Update SOPS-managed service secrets without shell-specific prompts."""

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
AGE_KEY = ROOT / ".age-key.txt"
SECRET_FILE = ROOT / "secrets/mashu.sops.yaml"

# Every native service consumes a key from this encrypted file.
SECRETS = {
    "tailscale": {
        "fields": (("Tailscale auth key", "tailscale_auth_key"),),
    },
    "argus": {
        "fields": (("GitHub token", "argus_github_token"),),
        "discord_webhook": True,
    },
    "forgejo": {
        "fields": (),
        "editor": True,
    },
    "backrest": {
        "fields": (),
        "editor": True,
    },
    "traefik": {
        "fields": (("Cloudflare API token", "cloudflare_dns_api_token"),),
    },
    "forgejo-runner": {
        "fields": (("Forgejo runner token", "forgejo_runner_registration_token"),),
    },
    "netdata": {
        "fields": (("Discord webhook URL", "netdata_discord_url"),),
    },
    "netdata-heartbeat": {
        "fields": (("HetrixTools heartbeat URL", "netdata_heartbeat_url"),),
    },
    "pocket-id": {
        "fields": (("Encryption key", "pocket_id_encryption_key"),),
    },
    "pomerium": {
        "fields": (
            ("Pocket ID client ID", "pomerium_idp_client_id"),
            ("Pocket ID client secret", "pomerium_idp_client_secret"),
            ("Cookie secret", "pomerium_cookie_secret"),
            ("Shared secret", "pomerium_shared_secret"),
        ),
    },
    "syncthing-heartbeat": {
        "fields": (("HetrixTools heartbeat URL", "syncthing_heartbeat_url"),),
    },
}


def sops_environment() -> dict[str, str]:
    if not AGE_KEY.is_file():
        raise RuntimeError(f"missing SOPS age identity: {AGE_KEY}")
    environment = os.environ.copy()
    environment["SOPS_AGE_KEY_FILE"] = str(AGE_KEY)
    return environment


def set_secret(
    path: Path,
    key: str,
    value: str,
    environment: dict[str, str],
) -> None:
    index = f'["{key}"]'
    subprocess.run(
        ["sops", "set", "--value-stdin", str(path), index],
        input=json.dumps(value),
        text=True,
        check=True,
        env=environment,
    )


def parse_discord_webhook(value: str) -> tuple[str, str]:
    url = urlsplit(value)
    parts = url.path.strip("/").split("/")
    if len(parts) == 5 and re.fullmatch(r"v[0-9]+", parts[1]):
        parts.pop(1)

    valid_hosts = {
        "discord.com",
        "canary.discord.com",
        "ptb.discord.com",
        "discordapp.com",
        "canary.discordapp.com",
        "ptb.discordapp.com",
    }
    if (
        url.scheme != "https"
        or url.hostname not in valid_hosts
        or url.query
        or url.fragment
        or len(parts) != 4
        or parts[:2] != ["api", "webhooks"]
        or not parts[2].isdigit()
        or not parts[3]
    ):
        raise ValueError("expected a Discord URL ending in /api/webhooks/ID/TOKEN")
    return parts[2], parts[3]


def update(service: str) -> None:
    secret = SECRETS[service]
    path = SECRET_FILE
    environment = sops_environment()

    if secret.get("editor"):
        subprocess.run(["sops", str(path)], check=True, env=environment)
        return

    updates = {}
    for label, key in secret["fields"]:
        value = getpass.getpass(f"{label} (leave empty to keep): ")
        if value:
            updates[key] = value

    if secret.get("discord_webhook"):
        webhook_url = getpass.getpass("Discord webhook URL (leave empty to keep): ")
        if webhook_url:
            webhook_id, webhook_token = parse_discord_webhook(webhook_url)
            updates["argus_discord_webhook_id"] = webhook_id
            updates["argus_discord_token"] = webhook_token

    for key, value in updates.items():
        set_secret(path, key, value, environment)

    if updates:
        print(f"Updated {path.relative_to(ROOT)}")
    else:
        print("No secret values changed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", nargs="?", metavar="SERVICE")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        return args
    if not args.service:
        parser.error(
            "missing service. Use: make secret service=<service>. "
            "Run 'make help' for available services."
        )
    if args.service not in SECRETS:
        parser.error(
            f"unknown service {args.service!r}. "
            f"Available services: {', '.join(sorted(SECRETS))}"
        )
    return args


def main() -> int:
    args = parse_args()
    if args.list:
        for service in sorted(SECRETS):
            print(f"  {service}")
        return 0
    try:
        update(args.service)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
