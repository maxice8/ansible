#!/usr/bin/env python3
"""Update pinned host, chart, and container versions."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(r"[0-9]+(?:\.[0-9]+)+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?")


@dataclass(frozen=True)
class Edit:
    path: str
    pattern: str


@dataclass(frozen=True)
class Component:
    edits: tuple[Edit, ...]
    suffix: str = ""


def image(path: str, repository: str) -> Edit:
    return Edit(path, rf"({re.escape(repository)}:)([^\s]+)")


def chart(path: str, repository: str, name: str) -> Edit:
    return Edit(
        path,
        rf"(repoURL: {re.escape(repository)}\s+chart: {re.escape(name)}"
        rf"\s+targetRevision:\s+)([^\s]+)",
    )


COMPONENTS = {
    "argocd": Component(
        (
            Edit(
                "inventory.py",
                r'("argocd":\s*\{[^}]*?"version":\s*")([^"]+)',
            ),
        ),
    ),
    "k3s": Component(
        (
            Edit(
                "inventory.py",
                r'("k3s":\s*\{[^}]*?"version":\s*")([^"]+)',
            ),
        ),
    ),
    "gateway-api": Component(
        (
            Edit(
                "kubernetes/platform/gateway-api/kustomization.yaml",
                r"(releases/download/v)([^/\s]+)(?=/standard-install\.yaml)",
            ),
        ),
    ),
    "rancher-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/rancher.yaml",
                "https://releases.rancher.com/server-charts/latest",
                "rancher",
            ),
        )
    ),
    "traefik-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/traefik.yaml",
                "https://traefik.github.io/charts",
                "traefik",
            ),
        )
    ),
    "traefik-image": Component(
        (
            Edit(
                "kubernetes/clusters/mashu/traefik.yaml",
                r"(image:\s+tag:\s+)([^\s]+)",
            ),
        ),
    ),
    "cert-manager-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/cert-manager.yaml",
                "https://charts.jetstack.io",
                "cert-manager",
            ),
        ),
    ),
    "sops-secrets-operator-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/sops-secrets-operator.yaml",
                "https://isindir.github.io/sops-secrets-operator",
                "sops-secrets-operator",
            ),
        )
    ),
    "netdata-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/netdata.yaml",
                "https://netdata.github.io/helmchart/",
                "netdata",
            ),
        )
    ),
    "argus": Component(
        (
            image(
                "kubernetes/apps/argus/deployment.yaml", "docker.io/releaseargus/argus"
            ),
        )
    ),
    "archisteamfarm": Component(
        (
            image(
                "kubernetes/apps/asf/deployment.yaml",
                "docker.io/justarchi/archisteamfarm",
            ),
        )
    ),
    "backrest": Component(
        (
            image(
                "kubernetes/platform/backrest/deployment.yaml",
                "ghcr.io/garethgeorge/backrest",
            ),
        ),
    ),
    "forgejo-chart": Component(
        (
            chart(
                "kubernetes/clusters/mashu/forgejo.yaml",
                "code.forgejo.org/forgejo-helm",
                "forgejo",
            ),
        )
    ),
    "forgejo": Component(
        (
            Edit(
                "kubernetes/clusters/mashu/forgejo.yaml",
                r"(image:\s+tag:\s+)([^\s]+)",
            ),
        )
    ),
    "forgejo-runner": Component(
        (
            image(
                "kubernetes/apps/forgejo/runner-deployment.yaml",
                "code.forgejo.org/forgejo/runner",
            ),
        )
    ),
    "docker-dind": Component(
        (
            Edit(
                "kubernetes/apps/forgejo/runner-deployment.yaml",
                r"(docker\.io/library/docker:)([^\s]+)",
            ),
        ),
        suffix="-dind",
    ),
    "netbird-client": Component(
        (
            Edit(
                "inventory.py",
                r'("netbird":\s*\{[^}]*?"version":\s*")([^"]+)',
            ),
        )
    ),
    "netbird-server": Component(
        (
            image(
                "kubernetes/apps/netbird/deployments.yaml",
                "docker.io/netbirdio/netbird-server",
            ),
        )
    ),
    "netbird-dashboard": Component(
        (
            image(
                "kubernetes/apps/netbird/deployments.yaml",
                "docker.io/netbirdio/dashboard",
            ),
        ),
    ),
    "pingvin-share": Component(
        (
            image(
                "kubernetes/apps/pingvin-share/deployment.yaml",
                "docker.io/smp46/pingvin-share-x",
            ),
        ),
    ),
    "pocket-id": Component(
        (
            image(
                "kubernetes/apps/pocket-id/deployment.yaml",
                "ghcr.io/pocket-id/pocket-id",
            ),
        ),
    ),
    "pomerium": Component(
        (
            image(
                "kubernetes/apps/pomerium/deployment.yaml",
                "docker.io/pomerium/pomerium",
            ),
        ),
    ),
    "syncthing": Component(
        (
            image(
                "kubernetes/apps/syncthing/deployment.yaml",
                "docker.io/syncthing/syncthing",
            ),
        )
    ),
    "whoami": Component(
        (image("kubernetes/apps/whoami/deployment.yaml", "docker.io/traefik/whoami"),),
    ),
    "yq": Component(
        (
            image(
                "kubernetes/platform/backrest/deployment.yaml", "docker.io/mikefarah/yq"
            ),
        )
    ),
}

COMPONENTS["netbird"] = Component(
    COMPONENTS["netbird-client"].edits + COMPONENTS["netbird-server"].edits
)


def normalize_version(raw_version: str, component: Component) -> str:
    version = raw_version.removeprefix("v")
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError(f"invalid version: {raw_version!r}")
    if component.suffix and version.endswith(component.suffix):
        version = version[: -len(component.suffix)]
    return version


def download_sha256(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "homelab-version-updater"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return hashlib.sha256(response.read()).hexdigest()
    except (OSError, urllib.error.URLError) as error:
        raise RuntimeError(f"failed to download {url}: {error}") from error


def replace_once(
    contents: dict[Path, str],
    edit: Edit,
    value: str | Callable[[str], str],
) -> tuple[str, str]:
    path = ROOT / edit.path
    text = contents.setdefault(path, path.read_text())
    regex = re.compile(edit.pattern, re.MULTILINE)
    matches = list(regex.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one version match in {edit.path}, found {len(matches)}"
        )
    old_value = matches[0].group(2)
    new_value = value(old_value) if callable(value) else value
    contents[path] = regex.sub(
        lambda match: f"{match.group(1)}{new_value}", text, count=1
    )
    return old_value, new_value


def update(component_name: str, raw_version: str, dry_run: bool) -> None:
    component = COMPONENTS[component_name]
    plain_version = normalize_version(raw_version, component)
    contents: dict[Path, str] = {}
    changes: list[tuple[str, str, str]] = []

    for edit in component.edits:
        old, new = replace_once(
            contents,
            edit,
            lambda current: (
                f"{'v' if current.startswith('v') else ''}"
                f"{plain_version}{component.suffix}"
            ),
        )
        changes.append((edit.path, old, new))

    if component_name == "argocd":
        url = (
            "https://raw.githubusercontent.com/argoproj/argo-cd/"
            f"v{plain_version}/manifests/install.yaml"
        )
        checksum = download_sha256(url)
        checksum_edit = Edit(
            "inventory.py",
            r'("argocd":\s*\{[^}]*?"manifest_sha256":\s*")([0-9a-f]{64})',
        )
        old, new = replace_once(contents, checksum_edit, checksum)
        changes.append((checksum_edit.path, old, new))

    if component_name == "k3s":
        encoded_version = urllib.parse.quote(f"v{plain_version}", safe="")
        url = (
            f"https://raw.githubusercontent.com/k3s-io/k3s/{encoded_version}/install.sh"
        )
        checksum = download_sha256(url)
        checksum_edit = Edit(
            "inventory.py",
            r'("k3s":\s*\{[^}]*?"installer_sha256":\s*")([0-9a-f]{64})',
        )
        old, new = replace_once(contents, checksum_edit, checksum)
        changes.append((checksum_edit.path, old, new))

    changed_paths = [
        path for path, new_text in contents.items() if new_text != path.read_text()
    ]
    action = "Would update" if dry_run else "Updated"
    for path, old, new in changes:
        if old != new:
            print(f"{action} {path}: {old} -> {new}")

    if not changed_paths:
        print(f"{component_name} is already at {changes[0][2]}")
        return

    if not dry_run:
        for path in changed_paths:
            path.write_text(contents[path])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", nargs="?", choices=sorted(COMPONENTS))
    parser.add_argument("version", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        return args
    if not args.component or not args.version:
        parser.error("component and version are required")
    return args


def main() -> int:
    args = parse_args()
    if args.list:
        for component in sorted(COMPONENTS):
            print(f"  {component}")
        return 0
    try:
        update(args.component, args.version, args.dry_run)
    except (RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
