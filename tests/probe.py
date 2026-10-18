"""Synthetic service: perform security probes inside the real service sandbox."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

STATE = Path("/var/lib/data/homelab-probe")
SECRET = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "probe").read_bytes()
VERSION = os.environ["PROBE_VERSION"]
if not (STATE / "persistent").exists():
    (STATE / "persistent").write_text("preserve across deployments and reboots\n")


def denied(action):
    try:
        action()
    except OSError:
        return True
    return False


def connect(address, port=18081):
    with socket.create_connection((address, port), timeout=1):
        pass


def bind_forbidden():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 18084))


def network_checks():
    connect("127.0.0.1")
    connect("::1")
    return {
        "loopback_ipv4_allowed": True,
        "loopback_ipv6_allowed": True,
        "sibling_listener_denied": denied(lambda: connect("127.0.0.1", 18082)),
        "sibling_listener_ipv6_denied": denied(lambda: connect("::1", 18082)),
        "nonloopback_ipv4_denied": denied(lambda: connect("192.0.2.1")),
        "nonloopback_ipv6_denied": denied(lambda: connect("2001:db8::1")),
        "metadata_denied": denied(lambda: connect("169.254.169.254")),
    }


def checks():
    (STATE / "writable").write_text("fixture\n")
    Path("/tmp/homelab-private-tmp").write_text("fixture\n")
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    child = json.loads(
        subprocess.check_output(
            [sys.executable, __file__, "child-checks"], text=True, timeout=30
        )
    )
    return {
        **network_checks(),
        **{f"child_{name}": value for name, value in child.items()},
        "own_state_writable": True,
        "dedicated_uid": os.getuid() == 62000,
        "dedicated_gid": os.getgid() == 62000,
        "state_mode": oct(STATE.stat().st_mode & 0o777),
        "sibling_data_denied": denied(
            lambda: Path("/var/lib/data/homelab-other/marker").read_text()
        ),
        "sibling_secret_denied": denied(
            lambda: Path("/run/homelab-other-secret").read_text()
        ),
        "host_write_denied": denied(
            lambda: Path("/opt/homelab-world-writable/forbidden").write_text("no\n")
        ),
        "host_tmp_hidden": not Path("/tmp/homelab-host-marker").exists(),
        "capabilities_empty": int(status["CapEff"].strip(), 16) == 0,
        "no_new_privileges": status["NoNewPrivs"].strip() == "1",
        "other_bind_denied": denied(bind_forbidden),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        result = (
            checks()
            if self.path == "/checks"
            else {
                "version": VERSION,
                "pid": os.getpid(),
                "secret_hash": hashlib.sha256(SECRET).hexdigest(),
            }
        )
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if sys.argv[1:] == ["child-checks"]:
        print(json.dumps(network_checks()))
    else:
        HTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
