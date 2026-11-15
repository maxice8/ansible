"""Run deployment checks on Mashu. This file is sent over SSH."""

import json
import os
import pwd
import socket
import struct
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager

UNITS = [
    "ssh",
    "tailscaled",
    "systemd-resolved",
    "homelab-firewall",
    "unbound",
    "unbound-network",
    "traefik",
    "pomerium",
    "pocket-id",
    "syncthing",
    "forgejo",
    "argus",
    "archisteamfarm",
    "pingvin-share",
    "pingvin-share-frontend",
    "netdata",
    "forgejo-runner",
    "runner-engine",
    "backrest",
]

ENDPOINTS = [
    ("Traefik", 9080, "/ping"),
    ("Pomerium", 28080, "/readyz"),
    ("Pocket ID", 1411, "/.well-known/openid-configuration"),
    ("Syncthing", 8384, "/rest/noauth/health"),
    ("Forgejo", 3000, "/api/healthz"),
    ("Argus", 8081, "/api/v1/healthcheck"),
    ("ArchiSteamFarm", 1242, "/"),
    ("Pingvin Share frontend", 3001, "/"),
    ("Pingvin Share API", 3002, "/api/health"),
    ("Netdata", 19999, "/api/v1/info"),
    ("Backrest", 9898, "/"),
]


@contextmanager
def check(label):
    print("CHECK\t" + label, flush=True)
    yield
    print("PASS\t" + label, flush=True)


def storage():
    print("GROUP\tStorage", flush=True)
    for label, path in [("Nix store", "/nix"), ("Application data", "/var/lib/data")]:
        with check(label + " · free space and inodes"):
            status = os.statvfs(path)
            # Keep a minimum reserve for activation and application writes.
            assert status.f_bavail * status.f_frsize >= 1024**3, (
                f"{path}: less than 1 GiB free"
            )
            assert status.f_favail >= 10000, f"{path}: fewer than 10000 free inodes"


def service_state():
    output = subprocess.check_output(
        [
            "systemctl",
            "show",
            *UNITS,
            "-p",
            "Id",
            "-p",
            "ActiveState",
            "-p",
            "NRestarts",
            "-p",
            "MainPID",
        ],
        text=True,
        timeout=10,
    )
    states = {}
    for block in output.strip().split("\n\n"):
        fields = dict(line.split("=", 1) for line in block.splitlines())
        assert fields["ActiveState"] == "active", fields["Id"] + " is not active"
        states[fields["Id"]] = (int(fields["NRestarts"]), int(fields["MainPID"]))
    assert len(states) == len(UNITS), "Missing managed service state"
    return states


def application_dns():
    with check("Application resolver"):
        pid = int(
            subprocess.check_output(
                ["systemctl", "show", "forgejo-runner", "-p", "MainPID", "--value"],
                text=True,
                timeout=10,
            )
        )
        assert pid > 0, "Forgejo runner is not running"
        user = pwd.getpwnam("forgejo-runner")
        probe = """import socket
from pathlib import Path
assert 'nameserver 127.0.0.1' in Path('/etc/resolv.conf').read_text().splitlines(), 'Application resolver is not Unbound'
socket.getaddrinfo('git.maxice8.com',443,type=socket.SOCK_STREAM)
"""
        subprocess.run(
            [
                "/usr/bin/nsenter",
                "--target",
                str(pid),
                "--mount",
                "--",
                "/usr/bin/setpriv",
                "--reuid",
                str(user.pw_uid),
                "--regid",
                str(user.pw_gid),
                "--clear-groups",
                "/usr/bin/python3",
                "-c",
                probe,
            ],
            check=True,
            timeout=15,
        )


def engine_api(method, path, data=None):
    command = [
        "/usr/bin/curl",
        "--silent",
        "--show-error",
        "--noproxy",
        "*",
        "--max-time",
        "10",
        "--write-out",
        "\n%{http_code}",
        "--unix-socket",
        "/run/runner-engine/podman.sock",
        "-X",
        method,
    ]
    if data is not None:
        command += ["--json", json.dumps(data)]
    output = subprocess.check_output(
        command + ["http://localhost/v1.41" + path], text=True, timeout=15
    )
    body, status = output.rsplit("\n", 1)
    if method == "DELETE" and status == "404":
        return None
    assert 200 <= int(status) < 300, f"Runner API {method} {path}: HTTP {status}"
    return json.loads(body) if body.strip() else None


def runner_dns():
    with check("Runner container resolution"):
        images = engine_api("GET", "/images/json")
        image = next(
            (
                entry["Id"]
                for entry in images
                if any(
                    tag.startswith("docker.io/library/alpine:")
                    for tag in entry.get("RepoTags") or []
                )
            ),
            None,
        )
        assert image, (
            "No cached Alpine image for the runner DNS probe; no image was pulled"
        )
        name = "mashu-deploy-dns-" + uuid.uuid4().hex
        try:
            engine_api(
                "POST",
                "/containers/create?name=" + name,
                {
                    "Image": image,
                    "Cmd": ["nslookup", "git.maxice8.com"],
                    "HostConfig": {
                        "CapDrop": ["ALL"],
                        "SecurityOpt": ["no-new-privileges"],
                        "Memory": 64 * 1024**2,
                        "PidsLimit": 32,
                    },
                },
            )
            engine_api("POST", f"/containers/{name}/start")
            result = engine_api("POST", f"/containers/{name}/wait")
            assert result["StatusCode"] == 0, "Runner container DNS lookup failed"
        finally:
            engine_api("DELETE", f"/containers/{name}?force=true&v=true")


def receive(connection, length):
    result = b""
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        assert chunk, "Truncated DNS response"
        result += chunk
    return result


def health(probe_runner=True):
    print("GROUP\tHost", flush=True)
    with check("Managed services"):
        for unit in UNITS:
            subprocess.run(["systemctl", "is-active", "--quiet", unit], check=True)
        failed = subprocess.check_output(
            ["systemctl", "--failed", "--no-legend", "--plain"], text=True
        ).strip()
        assert not failed, failed
    with check("Tailscale status"):
        status = json.loads(
            subprocess.check_output(["tailscale", "status", "--json"], text=True)
        )
        assert status["BackendState"] == "Running" and status["Self"]["Online"], (
            "Tailscale offline"
        )
    print("GROUP\tDNS", flush=True)
    with check("System resolution"):
        socket.getaddrinfo("id.maxice8.com", 443, type=socket.SOCK_STREAM)
    query = (
        struct.pack("!6H", 0x5281, 0x0100, 1, 0, 0, 0)
        + b"\x0acloudflare\x03com\0"
        + struct.pack("!HH", 1, 1)
    )
    for kind in [socket.SOCK_DGRAM, socket.SOCK_STREAM]:
        label = "Unbound UDP" if kind == socket.SOCK_DGRAM else "Unbound TCP"
        print("CHECK\t" + label, flush=True)
        with socket.socket(socket.AF_INET, kind) as connection:
            connection.settimeout(10)
            connection.connect(("127.0.0.1", 53))
            if kind == socket.SOCK_STREAM:
                connection.sendall(struct.pack("!H", len(query)) + query)
                response = receive(
                    connection, struct.unpack("!H", receive(connection, 2))[0]
                )
            else:
                connection.send(query)
                response = connection.recv(4096)
        ident, flags, _questions, answers, _authority, _additional = struct.unpack(
            "!6H", response[:12]
        )
        assert ident == 0x5281 and flags & 15 == 0 and answers > 0, (
            "Unbound resolution failed"
        )
        print("PASS\t" + label, flush=True)
    application_dns()
    if probe_runner:
        runner_dns()
    print("GROUP\tApplications", flush=True)
    deadline = time.monotonic() + 65

    def check_endpoint(endpoint):
        _name, port, path = endpoint
        status = subprocess.check_output(
            [
                "/usr/bin/curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--noproxy",
                "*",
                "--write-out",
                "%{http_code}",
                "--output",
                "/dev/null",
                "--retry",
                "60",
                "--retry-max-time",
                "60",
                "--retry-all-errors",
                "--retry-delay",
                "1",
                "--max-time",
                "5",
                f"http://127.0.0.1:{port}{path}",
            ],
            text=True,
            timeout=max(0.001, deadline - time.monotonic()),
        )
        assert status == "200", (port, status)

    with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
        pending = {
            pool.submit(check_endpoint, endpoint): endpoint[0] for endpoint in ENDPOINTS
        }
        for future in as_completed(pending):
            print("CHECK\t" + pending[future], flush=True)
            future.result()
            print("PASS\t" + pending[future], flush=True)
