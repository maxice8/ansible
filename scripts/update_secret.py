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

SECRETS = {
    "argus": {
        "file": "kubernetes/apps/argus/credentials.sops.yaml",
        "fields": (("GitHub token", "GITHUB_TOKEN"),),
        "discord_webhook": True,
    },
    "backrest": {
        "file": "kubernetes/platform/backrest/credentials.sops.yaml",
        "fields": (),
        "editor": True,
    },
    "cert-manager": {
        "file": (
            "kubernetes/platform/certificate-issuers/cloudflare-api-token.sops.yaml"
        ),
        "fields": (("Cloudflare API token", "api-token"),),
    },
    "forgejo-runner": {
        "file": "kubernetes/apps/forgejo-runner/credentials.sops.yaml",
        "fields": (("Forgejo runner token", "FORGEJO_RUNNER_TOKEN"),),
    },
    "netbird": {
        "file": "kubernetes/apps/netbird/credentials.sops.yaml",
        "fields": (),
        "editor": True,
    },
    "netdata": {
        "file": "kubernetes/apps/netdata/notifications.sops.yaml",
        "fields": (("Discord webhook URL", "NETDATA_DISCORD_WEBHOOK_URL"),),
    },
    "pocket-id": {
        "file": "kubernetes/apps/pocket-id/credentials.sops.yaml",
        "fields": (("Encryption key", "ENCRYPTION_KEY"),),
    },
    "pomerium": {
        "file": "kubernetes/apps/pomerium/credentials.sops.yaml",
        "fields": (
            ("Pocket ID client ID", "IDP_CLIENT_ID"),
            ("Pocket ID client secret", "IDP_CLIENT_SECRET"),
            ("Cookie secret", "COOKIE_SECRET"),
        ),
    },
}


def sops_environment() -> dict[str, str]:
    if not AGE_KEY.is_file():
        raise RuntimeError(f"missing SOPS age identity: {AGE_KEY}")
    environment = os.environ.copy()
    environment["SOPS_AGE_KEY_FILE"] = str(AGE_KEY)
    return environment


def set_secret(path: Path, key: str, value: str, environment: dict[str, str]) -> None:
    index = f'["spec"]["secretTemplates"][0]["stringData"]["{key}"]'
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
    path = ROOT / secret["file"]
    environment = sops_environment()

    if secret.get("editor"):
        subprocess.run(["sops", str(path)], check=True, env=environment)
        return

    changed = 0
    for label, key in secret["fields"]:
        value = getpass.getpass(f"{label} (leave empty to keep): ")
        if value:
            set_secret(path, key, value, environment)
            changed += 1

    if secret.get("discord_webhook"):
        webhook_url = getpass.getpass("Discord webhook URL (leave empty to keep): ")
        if webhook_url:
            webhook_id, webhook_token = parse_discord_webhook(webhook_url)
            set_secret(path, "DISCORD_WEBHOOK_ID", webhook_id, environment)
            set_secret(path, "DISCORD_TOKEN", webhook_token, environment)
            changed += 1

    if changed:
        print(f"Updated {secret['file']}")
    else:
        print("No secret values changed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", nargs="?", choices=sorted(SECRETS))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if not args.list and not args.service:
        parser.error("service is required")
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
