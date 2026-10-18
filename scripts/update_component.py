#!/usr/bin/env python3
"""Update pinned Nix releases and checksums; commit only the selected package file."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {
    "argus": "release-argus",
    "asf": "archisteamfarm",
    "forgejo": "forgejo",
    "pocket-id": "pocket-id",
    "pomerium": "pomerium",
    "syncthing": "syncthing",
    "tailscale": "tailscale",
    "traefik": "traefik",
}
LOCKED = {"forgejo-runner"}
ALIASES = {
    "archisteamfarm": "asf",
    "traefik-image": "traefik",
}
COMPONENTS = set(PACKAGES) | LOCKED
VERSION = re.compile(r'(\bversion = ")([^"\n]+)(")')
RELEASE = re.compile(
    r'((?:aarch64|x86_64)-linux = \{ arch = "([^"]+)"; sha256 = ")([a-f0-9]{64})(")'
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


def image_update(text: str, version: str) -> str:
    """Prefetch the pinned upstream ARM64 image, never the workstation architecture."""
    image = re.search(r'imageName = "([^"]+)"', text)
    if image is None:
        raise RuntimeError("missing upstream image name")
    result = subprocess.run(
        [
            "nix-prefetch-docker",
            "--image-name",
            image[1],
            "--image-tag",
            f"v{version}",
            "--arch",
            "arm64",
            "--os",
            "linux",
            "--json",
            "--quiet",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    pin = json.loads(result.stdout)
    if pin.get("imageName") != image[1] or pin.get("finalImageTag") != f"v{version}":
        raise RuntimeError("prefetch returned a different image or tag")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", pin["imageDigest"]):
        raise RuntimeError("invalid upstream image digest")
    # Accept Nix base32 or SRI hashes returned by the pinned prefetch tool.
    if not re.fullmatch(r"[0-9a-z]{52}|sha256-[A-Za-z0-9+/]{43}=", pin["hash"]):
        raise RuntimeError("invalid image archive hash")
    for key, value in {
        "imageDigest": pin["imageDigest"],
        "hash": pin["hash"],
        "finalImageTag": f"v{version}",
    }.items():
        text = replace_one(text, rf'({key} = ")([^"\n]+)(")', value)
    return text


def path_for(component: str) -> Path:
    name = (
        "pingvin-share-image" if component == "pingvin-share" else PACKAGES[component]
    )
    return ROOT / "pkgs" / f"{name}.nix"


def validate() -> None:
    for component in sorted(set(PACKAGES)):
        text = path_for(component).read_text()
        if component == "pingvin-share":
            for key in ["imageDigest", "hash", "finalImageTag"]:
                replace_one(text, rf'({key} = ")([^"\n]+)(")', "validation-only")
            if 'arch = "arm64"' not in text:
                raise RuntimeError("Pingvin image must select ARM64")
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
            f"{component} is provided by locked Nixpkgs; update the system-manager input deliberately, then rebuild and verify the selected package version"
        )
    version = version.removeprefix("v")
    if not re.fullmatch(
        r"[0-9]+(?:\.[0-9]+)+(?:[-+][0-9A-Za-z][0-9A-Za-z.-]*)?", version
    ):
        raise ValueError(f"invalid version: {version!r}")
    path = path_for(component)
    text = path.read_text()
    pattern = (
        r'finalImageTag = "v([^"\n]+)"'
        if component == "pingvin-share"
        else VERSION.pattern
    )
    match = re.search(pattern, text)
    if match is None:
        raise RuntimeError(f"missing version in {path.relative_to(ROOT)}")
    current = match[1] if component == "pingvin-share" else match[2]
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
        image_update(text, version)
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
            "use make update service=<component> version=<version>; make list shows supported components"
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
