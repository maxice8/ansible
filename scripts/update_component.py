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
    matches: int = 1


@dataclass(frozen=True)
class Component:
    edits: tuple[Edit, ...]
    suffix: str = ""


def image(path: str, repository: str, matches: int = 1) -> Edit:
    return Edit(path, rf"({re.escape(repository)}:)([^\s]+)", matches)


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
    "rancher": Component(
        (
            chart(
                "kubernetes/clusters/mashu/rancher.yaml",
                "https://releases.rancher.com/server-charts/latest",
                "rancher",
            ),
        )
    ),
    "rancher-compliance": Component(
        (
            chart(
                "kubernetes/clusters/mashu/rancher-compliance.yaml",
                "https://charts.rancher.io",
                "rancher-compliance-crd",
            ),
            chart(
                "kubernetes/clusters/mashu/rancher-compliance.yaml",
                "https://charts.rancher.io",
                "rancher-compliance",
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
    "cert-manager": Component(
        (
            chart(
                "kubernetes/clusters/mashu/cert-manager.yaml",
                "https://charts.jetstack.io",
                "cert-manager",
            ),
        ),
    ),
    "sops-secrets-operator": Component(
        (
            chart(
                "kubernetes/clusters/mashu/sops-secrets-operator.yaml",
                "https://isindir.github.io/sops-secrets-operator",
                "sops-secrets-operator",
            ),
        )
    ),
    "netdata": Component(
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
    "asf": Component(
        (
            image(
                "kubernetes/apps/asf/deployment.yaml",
                "docker.io/justarchi/archisteamfarm",
                matches=2,
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
                "kubernetes/apps/forgejo-runner/deployment.yaml",
                "code.forgejo.org/forgejo/runner",
            ),
        )
    ),
    "docker-dind": Component(
        (
            Edit(
                "kubernetes/apps/forgejo-runner/deployment.yaml",
                r"(docker\.io/library/docker:)([^\s]+)",
            ),
        ),
        suffix="-dind",
    ),
    "netbird": Component(
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
                "kubernetes/apps/netbird-dashboard/deployment.yaml",
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

ALIASES = {
    "archisteamfarm": "asf",
    "cert-manager-chart": "cert-manager",
    "netbird-server": "netbird",
    "netdata-chart": "netdata",
    "rancher-chart": "rancher",
    "rancher-compliance-chart": "rancher-compliance",
    "sops-secrets-operator-chart": "sops-secrets-operator",
}

ARGUS_CONFIG = ROOT / "kubernetes/apps/argus/config.yml"


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


def replace_matches(
    contents: dict[Path, str],
    edit: Edit,
    value: str | Callable[[str], str],
) -> tuple[str, str]:
    path = ROOT / edit.path
    try:
        text = contents.setdefault(path, path.read_text())
    except OSError as error:
        raise RuntimeError(f"failed to read {edit.path}: {error.strerror}") from error
    regex = re.compile(edit.pattern, re.MULTILINE)
    matches = list(regex.finditer(text))
    if len(matches) != edit.matches:
        raise RuntimeError(
            f"expected {edit.matches} version match(es) in {edit.path}, "
            f"found {len(matches)}"
        )
    old_values = {match.group(2) for match in matches}
    if len(old_values) != 1:
        raise RuntimeError(
            f"expected matching versions in {edit.path}, found "
            f"{', '.join(sorted(old_values))}"
        )
    old_value = old_values.pop()
    new_value = value(old_value) if callable(value) else value
    contents[path] = regex.sub(
        lambda match: f"{match.group(1)}{new_value}", text, count=edit.matches
    )
    return old_value, new_value


def validate() -> None:
    errors: list[str] = []
    for component_name, component in COMPONENTS.items():
        for edit in component.edits:
            try:
                replace_matches({}, edit, lambda current: current)
            except RuntimeError as error:
                errors.append(f"{component_name}: {error}")

    try:
        argus_config = ARGUS_CONFIG.read_text()
    except OSError as error:
        errors.append(
            f"failed to read {ARGUS_CONFIG.relative_to(ROOT)}: {error.strerror}"
        )
    else:
        _, separator, services_config = argus_config.partition("\nservice:\n")
        if not separator:
            errors.append("could not find the top-level Argus service map")
        else:
            argus_services = set(
                re.findall(r"^  ([a-z0-9][a-z0-9-]*):$", services_config, re.MULTILINE)
            )
            component_names = set(COMPONENTS)
            if argus_services != component_names:
                errors.append(
                    f"Argus-only services: {', '.join(sorted(argus_services - component_names)) or 'none'}; "
                    f"updater-only services: {', '.join(sorted(component_names - argus_services)) or 'none'}"
                )

    if errors:
        raise RuntimeError("\n".join(errors))

    print(f"Validated {len(COMPONENTS)} component mappings and matching Argus services")


def update(component_name: str, raw_version: str, dry_run: bool) -> None:
    component_name = ALIASES.get(component_name, component_name)
    component = COMPONENTS[component_name]
    plain_version = normalize_version(raw_version, component)
    contents: dict[Path, str] = {}
    changes: list[tuple[str, str, str]] = []

    for edit in component.edits:
        old, new = replace_matches(
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
        old, new = replace_matches(contents, checksum_edit, checksum)
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
        old, new = replace_matches(contents, checksum_edit, checksum)
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
    parser.add_argument(
        "component", nargs="?", choices=sorted(COMPONENTS.keys() | ALIASES.keys())
    )
    parser.add_argument("version", nargs="?")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list or args.check:
        return args
    if not args.component or not args.version:
        parser.error("component and version are required")
    return args


def main() -> int:
    args = parse_args()
    if args.check:
        try:
            validate()
        except RuntimeError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        return 0
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
