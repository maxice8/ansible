#!/usr/bin/env python3
"""Update pinned Nix releases and checksums; commit only the selected package file."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
    "asf": "archisteamfarm",
    "argus": "release-argus",
    "forgejo": "forgejo",
    "pingvin-share": "pingvin-share",
}
LOCKED = {
    "backrest",
    "forgejo-runner",
    "netdata",
    "pocket-id",
    "pomerium",
    "syncthing",
    "tailscale",
    "traefik",
}
ALIASES = {
    "archisteamfarm": "asf",
    "traefik-image": "traefik",
}
COMPONENTS = set(PACKAGES) | LOCKED
VERSION = re.compile(r'(\bversion = ")([^"\n]+)(")')
RELEASE = re.compile(
    r'((?:aarch64|x86_64)-linux\s*=\s*\{\s*arch\s*=\s*"([^"]+)";\s*sha256\s*=\s*")([a-f0-9]{64})(")'
)


def replace_one(text: str, pattern: str, value: str) -> str:
    """Require the exact pin layout rather than silently editing the wrong field."""
    regex = re.compile(pattern)
    if len(regex.findall(text)) != 1:
        raise RuntimeError(f"expected one match for {pattern!r}")
    return regex.sub(lambda m: m[1] + value + m[3], text)


def download_sha256(url: str) -> str:
    digest = hashlib.sha256()
    request = urllib.request.Request(
        url, headers={"User-Agent": "homelab-version-updater"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        while block := response.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def package_update(text: str, version: str) -> str:
    """Resolve the package's own release URL for both supported architectures."""
    text = replace_one(text, VERSION.pattern, version)
    urls = re.findall(r'\burl = "([^"\n]+)"', text)
    if len(urls) != 1:
        raise RuntimeError("expected one upstream release URL")
    url = urls[0].replace("${version}", version)
    releases = list(RELEASE.finditer(text))
    if releases:
        if len(releases) != 2:
            raise RuntimeError("expected ARM64 and x86_64 release checksums")
        hashes = {}
        for match in releases:
            resolved = url.replace("${release.arch}", match[2])
            if "${" in resolved:
                raise RuntimeError(f"unresolved release URL: {resolved}")
            hashes[match[2]] = download_sha256(resolved)
        return RELEASE.sub(lambda m: m[1] + hashes[m[2]] + m[4], text)
    if "${" in url:
        raise RuntimeError(f"unresolved release URL: {url}")
    return replace_one(text, r'(\bsha256 = ")([a-f0-9]{64})(")', download_sha256(url))


def pingvin_update(text: str, version: str) -> str:
    """Update the source, npm caches and matching Prisma engines together."""
    tag = f"refs/tags/v{version}"
    references = subprocess.check_output(
        [
            "git",
            "ls-remote",
            "https://github.com/smp46/pingvin-share-x.git",
            tag,
            tag + "^{}",
        ],
        text=True,
    )
    revisions = {
        name: revision
        for revision, name in (line.split() for line in references.splitlines())
    }
    revision = revisions.get(tag + "^{}", revisions.get(tag, ""))
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise RuntimeError("missing Pingvin release tag")
    source = json.loads(
        subprocess.check_output(
            [
                "nix",
                "flake",
                "prefetch",
                "--json",
                f"github:smp46/pingvin-share-x/{revision}",
            ],
            text=True,
        )
    )
    directory = Path(source["storePath"])
    locks = {
        name: json.loads((directory / name / "package-lock.json").read_text())
        for name in ["backend", "frontend"]
    }
    if any(lock["version"] != version for lock in locks.values()):
        raise RuntimeError("Pingvin tag and npm versions differ")
    packages = locks["backend"]["packages"]
    engine = re.fullmatch(
        r"(\d+\.\d+\.\d+)-\d+\.([a-f0-9]{40})",
        packages["node_modules/@prisma/engines-version"]["version"],
    )
    if engine is None or any(
        packages[f"node_modules/{name}"]["version"] != engine[1]
        for name in ["prisma", "@prisma/client"]
    ):
        raise RuntimeError("Prisma client and engine versions differ")
    pins = {
        "version": version,
        "rev": revision,
        "hash": source["hash"],
        "prismaVersion": engine[1],
        "engineRev": engine[2],
    }
    for name in locks:
        pins[f"{name}NpmDepsHash"] = subprocess.check_output(
            [
                "nix",
                "run",
                "--inputs-from",
                f"git+{ROOT.as_uri()}",
                "nixpkgs#prefetch-npm-deps",
                "--",
                str(directory / name / "package-lock.json"),
            ],
            text=True,
        ).strip()
    for name, value in pins.items():
        text = replace_one(text, rf'({name} = ")([^"\n]+)(")', value)
    for platform in ["debian-openssl-3.0.x", "linux-arm64-openssl-3.0.x"]:
        for key, filename in [
            ("query", "libquery_engine.so.node"),
            ("schema", "schema-engine"),
        ]:
            digest = download_sha256(
                f"https://binaries.prisma.sh/all_commits/{engine[2]}/{platform}/{filename}.gz"
            )
            value = "sha256-" + base64.b64encode(bytes.fromhex(digest)).decode()
            prefix = rf'platform = "{re.escape(platform)}";\s*'
            if key == "schema":
                prefix += r'query = "[^"]+";\s*'
            text = replace_one(text, rf'({prefix}{key} = ")([^"\n]+)(")', value)
    return text


def path_for(component: str) -> Path:
    return ROOT / "pkgs" / f"{PACKAGES[component]}.nix"


def validate() -> None:
    for component in sorted(PACKAGES):
        text = path_for(component).read_text()
        if component == "pingvin-share":
            for key in [
                "version",
                "rev",
                "hash",
                "prismaVersion",
                "engineRev",
                "backendNpmDepsHash",
                "frontendNpmDepsHash",
            ]:
                replace_one(text, rf'({key} = ")([^"\n]+)(")', "validation-only")
            if (
                len(
                    re.findall(
                        r'platform = "(?:debian|linux-arm64)-openssl-3\.0\.x"', text
                    )
                )
                != 2
            ):
                raise RuntimeError("Pingvin must pin both engine architectures")
        else:
            replace_one(text, VERSION.pattern, "validation-only")
            releases = RELEASE.findall(text)
            if (
                not releases
                and len(re.findall(r'\bsha256 = "[a-f0-9]{64}"', text)) != 1
            ):
                raise RuntimeError(f"{component}: missing release checksums")
            if releases and len(releases) != 2:
                raise RuntimeError(f"{component}: expected two architecture pins")
    selected = (
        (ROOT / "services/argus/default.nix")
        .read_text()
        .split("  selected = {", 1)[1]
        .split("\n  };", 1)[0]
    )
    names = {
        ALIASES.get(name, name)
        for name in re.findall(r"^    ([a-z0-9-]+) =", selected, re.MULTILINE)
    }
    if names != COMPONENTS - {"tailscale"}:
        raise RuntimeError(
            f"Argus/updater mapping mismatch: {names ^ (COMPONENTS - {'tailscale'})}"
        )
    print(
        f"Validated {len(COMPONENTS)} Nix component mappings; {', '.join(sorted(LOCKED))} use flake.lock"
    )


def update(component: str, version: str, dry_run: bool) -> None:
    if component in LOCKED:
        raise RuntimeError(
            f"{component} is provided by locked Nixpkgs; run 'make update inputs=nixpkgs', then rebuild and verify the selected package versions"
        )
    version = version.removeprefix("v")
    if not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?", version
    ):
        raise ValueError(f"invalid version: {version!r}")
    path = path_for(component)
    text = path.read_text()
    match = re.search(VERSION.pattern, text)
    if match is None:
        raise RuntimeError(f"missing version in {path.relative_to(ROOT)}")
    current = match[2]
    if current == version:
        print(f"{component} is already at {version}")
        return
    relative = str(path.relative_to(ROOT))
    if not dry_run:
        status = subprocess.check_output(
            ["git", "status", "--short", "--", relative], cwd=ROOT, text=True
        )
        if status:
            raise RuntimeError(
                f"refusing to overwrite or commit pre-existing component changes:\n{status.rstrip()}"
            )
    changed = (
        pingvin_update(text, version)
        if component == "pingvin-share"
        else package_update(text, version)
    )
    print(
        f"{'Would update' if dry_run else 'Updated'} {relative}: {current} -> {version} (including release checksums)"
    )
    if dry_run:
        return
    # All downloads and validation finish before any source file is changed.
    path.write_text(changed)
    subprocess.run(
        [
            "git",
            "commit",
            "--only",
            "-m",
            f"chore({component}): update to {version}",
            "--",
            relative,
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", nargs="?")
    parser.add_argument("version", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.list:
        for name in sorted(COMPONENTS):
            print(f"  {name}" + (" (flake.lock)" if name in LOCKED else ""))
        return 0
    if not args.check and (
        ALIASES.get(args.component, args.component) not in COMPONENTS
        or not args.version
    ):
        parser.error(
            "use make update <component> <version>; make list shows supported components"
        )
    try:
        if args.check:
            validate()
        else:
            update(
                ALIASES.get(args.component, args.component), args.version, args.dry_run
            )
    except (
        OSError,
        RuntimeError,
        ValueError,
        KeyError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
