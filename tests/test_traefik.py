"""Check native Traefik against synthetic backends, only inside the disposable VM."""

import base64
import hashlib
import http.client
import json
import os
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def require_vm():
    if os.geteuid() != 0 or socket.gethostname() != "mashu-test":
        raise RuntimeError("Run as root only inside the disposable mashu-test VM")


class Backend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = (
                self.headers["Sec-WebSocket-Key"]
                + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            )
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header(
                "Sec-WebSocket-Accept",
                base64.b64encode(hashlib.sha1(key.encode()).digest()).decode(),
            )
            self.end_headers()
            header = self.rfile.read(2)
            if len(header) != 2 or header[0] != 0x81 or header[1] != 0x85:
                return
            mask = self.rfile.read(4)
            payload = bytes(
                value ^ mask[index % 4]
                for index, value in enumerate(self.rfile.read(5))
            )
            self.wfile.write(b"\x81\x05" + payload)
            self.wfile.flush()
        elif self.server.server_port == 8080:
            self.send_response(302)
            self.send_header("Location", "https://pomerium.maxice8.com/sign-in")
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            body = json.dumps(
                {
                    "host": self.headers["Host"],
                    "proto": self.headers.get("X-Forwarded-Proto"),
                    "forwarded_for": self.headers.get("X-Forwarded-For"),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, *_):
        pass


def serve():
    for port in [1411, 3000, 3001, 8080, 8081]:
        server = ThreadingHTTPServer(
            ("0.0.0.0" if port == 8081 else "127.0.0.1", port), Backend
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


def check():
    subprocess.run(
        ["ip", "address", "replace", "198.51.100.1/32", "dev", "lo"], check=True
    )
    subprocess.run(
        ["ip", "address", "replace", "169.254.169.254/32", "dev", "lo"], check=True
    )
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "traefik-test-backends"], check=False
    )
    if active.returncode:
        subprocess.run(
            [
                "systemd-run",
                "--unit=traefik-test-backends",
                "/usr/bin/python3",
                __file__,
                "serve",
            ],
            check=True,
        )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", 8080), timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("Synthetic backend failed to start")

    context = ssl.create_default_context(cafile="/var/lib/data/traefik/test-cert.pem")

    def request(host, *, headers=None, address="127.0.0.1"):
        connection = http.client.HTTPConnection(host, 443, timeout=5)
        connection.sock = context.wrap_socket(
            socket.create_connection((address, 443), timeout=5), server_hostname=host
        )
        connection.request("GET", "/", headers={"Host": host, **(headers or {})})
        response = connection.getresponse()
        result = response.status, response.getheader("Location"), response.read()
        connection.close()
        return result

    direct = ["git.maxice8.com", "id.maxice8.com", "share.mashu.maxice8.com"]
    protected = [
        "pomerium.maxice8.com",
        *[
            f"{name}.mashu.maxice8.com"
            for name in ["argus", "asf", "backrest", "netdata", "syncthing"]
        ],
    ]
    for _ in range(60):
        try:
            if request(direct[0])[0] == 200:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("Native ingress did not become functional")
    for address in ["127.0.0.1", "::1"]:
        for host in direct:
            status, _, body = request(host, address=address)
            assert status == 200 and json.loads(body)["host"] == host
            assert json.loads(body)["proto"] == "https"
        for host in protected:
            status, location, _ = request(host, address=address)
            assert status == 302 and location == "https://pomerium.maxice8.com/sign-in"
        plain = http.client.HTTPConnection(address, 80, timeout=5)
        plain.request("GET", "/", headers={"Host": direct[0]})
        response = plain.getresponse()
        assert (
            response.status in [301, 308]
            and response.getheader("Location") == "https://git.maxice8.com/"
        )
        plain.close()
    assert request("missing.mashu.maxice8.com")[0] == 404
    _, _, body = request(
        direct[0],
        headers={"X-Forwarded-Proto": "http", "X-Forwarded-For": "192.0.2.123"},
    )
    echoed = json.loads(body)
    assert echoed["proto"] == "https" and "192.0.2.123" not in echoed["forwarded_for"]
    assert request(direct[0], headers={"X_Auth_User": "spoofed"})[0] == 400

    with context.wrap_socket(
        socket.create_connection(("127.0.0.1", 443), timeout=5),
        server_hostname=direct[0],
    ) as ws:
        ws.sendall(
            b"GET / HTTP/1.1\r\nHost: git.maxice8.com\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"  # Public test nonce. gitleaks:allow
        )
        header = b""
        while b"\r\n\r\n" not in header:
            part = ws.recv(4096)
            assert part, "WebSocket closed before upgrade"
            header += part
        assert header.startswith(b"HTTP/1.1 101"), header.split(b"\r\n", 1)[0]
        mask = b"abcd"
        ws.sendall(
            b"\x81\x85"
            + mask
            + bytes(value ^ mask[index % 4] for index, value in enumerate(b"hello"))
        )
        frame = b""
        while len(frame) < 7:
            part = ws.recv(7 - len(frame))
            assert part, "WebSocket closed before echo"
            frame += part
        assert frame == b"\x81\x05hello"

    # Controls prove both forbidden private/public-port targets are actually listening.
    for address in ["127.0.0.1", "169.254.169.254", "198.51.100.1"]:
        socket.create_connection((address, 8081), timeout=2).close()
    cgroup = subprocess.check_output(
        ["systemctl", "show", "traefik", "--property=ControlGroup", "--value"],
        text=True,
    ).strip()
    assert cgroup == "/system.slice/traefik.service"
    # Join only this short-lived VM child to the real service cgroup to test its BPF.
    code = """import errno, os, socket
from pathlib import Path
Path('/sys/fs/cgroup/system.slice/traefik.service/cgroup.procs').write_text(str(os.getpid()))
os.setgroups([]); os.setgid(62002); os.setuid(62002)
for family,address in [(socket.AF_INET,'127.0.0.1'),(socket.AF_INET6,'::1')]:
    with socket.socket(family) as probe: probe.bind((address,0))
    with socket.socket(family) as probe:
        try: probe.bind((address,18084))
        except OSError as error: assert error.errno in [errno.EPERM,errno.EACCES]
        else: raise AssertionError('Unexpected listening port allowed')
for address, port, expected in [('127.0.0.1',8080,True), ('127.0.0.1',8081,False),
                               ('169.254.169.254',8081,False), ('198.51.100.1',443,True),
                               ('198.51.100.1',8081,False)]:
    try:
        socket.create_connection((address,port),timeout=2).close(); allowed=True
    except OSError: allowed=False
    assert allowed==expected, (address,port,allowed)
"""
    with socket.socket() as control:
        control.bind(("127.0.0.1", 18084))
    subprocess.run(["/usr/bin/python3", "-c", code], check=True)
    pid = subprocess.check_output(
        ["systemctl", "show", "traefik", "--property=MainPID", "--value"], text=True
    ).strip()
    status = dict(
        line.split(":", 1)
        for line in Path(f"/proc/{pid}/status").read_text().splitlines()
    )
    assert status["Uid"].split()[0] == "62002" and status["NoNewPrivs"].strip() == "1"
    assert int(status["CapEff"].strip(), 16) == 1 << 10  # CAP_NET_BIND_SERVICE only.
    assert Path("/var/lib/data/traefik").stat().st_mode & 0o777 == 0o700
    subprocess.run(
        [
            "sudo",
            "-u",
            "traefik",
            "test",
            "!",
            "-r",
            "/run/secrets/cloudflare-dns-token",
        ],
        check=True,
    )
    print(
        json.dumps(
            {
                "routes_ipv4_ipv6": len(direct + protected) * 2,
                "http_redirects": True,
                "unknown_host_denied": True,
                "forwarded_header_spoof_denied": True,
                "identity_header_alias_denied": True,
                "websocket_bidirectional": True,
                "egress_controls": True,
                "uid_capabilities_credentials": True,
            }
        )
    )


if __name__ == "__main__":
    require_vm()
    if sys.argv[1:] == ["serve"]:
        serve()
    elif not sys.argv[1:]:
        check()
    else:
        raise ValueError(
            "Use no arguments for checks, or 'serve' for synthetic backends"
        )
