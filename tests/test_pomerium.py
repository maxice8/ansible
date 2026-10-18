"""Exercise real Pomerium with synthetic OIDC and backends in mashu-test only."""

import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

ROOT = Path("/run/pomerium-fixture")
HOSTS = ["asf", "syncthing", "netdata", "backrest", "argus"]
PORTS = [1242, 8384, 19999, 9898, 8081]
ISSUER = "http://127.0.0.1:1411"


def require_vm():
    if os.geteuid() != 0 or socket.gethostname() != "mashu-test":
        raise RuntimeError("Run as root only in the disposable mashu-test VM")


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class Backend(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        # A protected upstream must never see an unauthenticated request.
        with (ROOT / "backend-hits").open("a") as log:
            log.write(str(self.server.server_port) + "\n")
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
            assert self.rfile.read(2) == b"\x81\x85"
            mask = self.rfile.read(4)
            payload = bytes(v ^ mask[i % 4] for i, v in enumerate(self.rfile.read(5)))
            self.wfile.write(b"\x81\x05" + payload)
            self.wfile.flush()
            return
        body = json.dumps({"fixture_backend": self.server.server_port}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class Issuer(Backend):
    protocol_version = "HTTP/1.0"
    codes: ClassVar[dict] = {}

    def send(self, body):
        body = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/.well-known/openid-configuration":
            self.send(
                {
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/authorize",
                    "token_endpoint": ISSUER + "/token",
                    "jwks_uri": ISSUER + "/jwks",
                    "userinfo_endpoint": ISSUER + "/userinfo",
                    "response_types_supported": ["code"],
                    "subject_types_supported": ["public"],
                    "id_token_signing_alg_values_supported": ["RS256"],
                    "token_endpoint_auth_methods_supported": [
                        "client_secret_basic",
                        "client_secret_post",
                    ],
                }
            )
        elif url.path == "/jwks":
            modulus = (
                subprocess.check_output(
                    [
                        "openssl",
                        "rsa",
                        "-in",
                        str(ROOT / "issuer.key"),
                        "-noout",
                        "-modulus",
                    ],
                    stderr=subprocess.DEVNULL,
                )
                .decode()
                .strip()
                .split("=")[1]
            )
            self.send(
                {
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": "fixture",
                            "use": "sig",
                            "alg": "RS256",
                            "n": b64(bytes.fromhex(modulus)),
                            "e": "AQAB",
                        }
                    ]
                }
            )
        elif url.path == "/authorize":
            query = parse_qs(url.query)
            assert query["client_id"] == ["fixture-client"]
            assert query["redirect_uri"] == [
                "https://pomerium.maxice8.com/oauth2/callback"
            ]
            code = secrets.token_urlsafe(16)
            self.codes[code] = query.get("nonce", [""])[0]
            self.send_response(302)
            self.send_header(
                "Location",
                query["redirect_uri"][0]
                + "?"
                + urlencode({"code": code, "state": query["state"][0]}),
            )
            self.end_headers()
        elif url.path == "/userinfo":
            self.send(
                {
                    "sub": "fixture-user",
                    "email": "fixture@example.invalid",
                    "email_verified": True,
                }
            )
        else:
            self.send_error(404)

    def do_POST(self):
        assert self.path == "/token"
        query = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if self.headers.get("Authorization", "").startswith("Basic "):
            pair = base64.b64decode(self.headers["Authorization"][6:]).decode()
            assert pair == "fixture-client:fixture-client-secret"
        else:
            assert query["client_id"] == ["fixture-client"] and query[
                "client_secret"
            ] == ["fixture-client-secret"]
        nonce = self.codes.pop(query["code"][0])
        claims = {
            "iss": ISSUER,
            "sub": "fixture-user",
            "aud": "fixture-client",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
            "nonce": nonce,
            "email": "fixture@example.invalid",
            "email_verified": True,
        }
        unsigned = (
            b64(json.dumps({"alg": "RS256", "kid": "fixture"}).encode())
            + "."
            + b64(json.dumps(claims).encode())
        )
        signature = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", str(ROOT / "issuer.key")],
            input=unsigned.encode(),
            capture_output=True,
            check=True,
        ).stdout
        self.send(
            {
                "access_token": "fixture-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": unsigned + "." + b64(signature),
            }
        )


def serve():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    if not (ROOT / "issuer.key").exists():
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(ROOT / "issuer.key"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        (ROOT / "issuer.key").chmod(0o600)
    for port, handler in [
        (1411, Issuer),
        *[(p, Backend) for p in PORTS],
        (18084, Backend),
    ]:
        server = ThreadingHTTPServer(
            ("0.0.0.0" if port == 18084 else "127.0.0.1", port), handler
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Event().wait()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def browser(jar=None, redirects=True):
    context = ssl.create_default_context(cafile="/var/lib/data/traefik/test-cert.pem")
    return build_opener(
        ProxyHandler({}),
        HTTPSHandler(context=context),
        HTTPCookieProcessor(jar if jar is not None else CookieJar()),
        *([] if redirects else [NoRedirect()]),
    )


def get(opener, url, headers=None):
    try:
        response = opener.open(Request(url, headers=headers or {}), timeout=15)
    except HTTPError as response:
        return response.code, response.headers, response.read(), response.url
    with response:
        return response.status, response.headers, response.read(), response.url


def isolation_check():
    subprocess.run(
        ["ip", "address", "replace", "169.254.169.254/32", "dev", "lo"], check=True
    )
    # This independent control is outside Traefik's own metadata-address restrictions.
    for address, port in [
        ("127.0.0.1", 22),
        ("127.0.0.1", 18084),
        ("169.254.169.254", 18084),
    ]:
        socket.create_connection((address, port), timeout=2).close()
    code = """import errno,os,socket
from pathlib import Path
from typing import ClassVar
Path('/sys/fs/cgroup/system.slice/pomerium.service/cgroup.procs').write_text(str(os.getpid()))
os.setgroups([]);os.setgid(62003);os.setuid(62003)
for address,port,expected in [('127.0.0.1',1242,True),('127.0.0.53',53,True),('127.0.0.1',22,False),('127.0.0.1',18084,False),('169.254.169.254',18084,False)]:
 try:socket.create_connection((address,port),timeout=2).close();allowed=True
 except OSError:allowed=False
 assert allowed==expected,(address,port,allowed)
for family,address in [(socket.AF_INET,'127.0.0.1'),(socket.AF_INET6,'::1')]:
 with socket.socket(family) as s:s.bind((address,0))
 with socket.socket(family) as s:
  try:s.bind((address,18085))
  except OSError as e:assert e.errno in [errno.EACCES,errno.EPERM]
  else:raise AssertionError('Unapproved named bind permitted')
try:Path('/var/lib/data/traefik/test-key.pem').read_bytes()
except PermissionError:pass
else:raise AssertionError('Another service private key was readable')
"""
    subprocess.run(["/usr/bin/python3", "-c", code], check=True)


def websocket_check(jar):
    host = "argus.mashu.maxice8.com"
    request = Request("https://" + host + "/")
    jar.add_cookie_header(request)
    context = ssl.create_default_context(cafile="/var/lib/data/traefik/test-cert.pem")
    with context.wrap_socket(
        socket.create_connection(("127.0.0.1", 443), timeout=10), server_hostname=host
    ) as connection:
        key = base64.b64encode(b"synthetic-ws-key").decode()
        headers = (
            f"GET / HTTP/1.1\r\nHost: {host}\r\nCookie: {request.get_header('Cookie')}\r\n"
            f"Connection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
        )
        connection.sendall(headers.encode())
        response = b""
        while not response.endswith(b"\r\n\r\n"):
            byte = connection.recv(1)
            assert byte, response
            response += byte
        assert response.startswith(b"HTTP/1.1 101"), response[:200]
        mask = b"abcd"
        connection.sendall(
            b"\x81\x85" + mask + bytes(v ^ mask[i % 4] for i, v in enumerate(b"hello"))
        )
        stream = connection.makefile("rb")
        assert stream.read(7) == b"\x81\x05hello"


def check():
    ROOT.mkdir(mode=0o700, exist_ok=True)
    names = ["pomerium.maxice8.com", *[h + ".mashu.maxice8.com" for h in HOSTS]]
    hosts = Path("/etc/hosts")
    if "# pomerium-fixture" not in hosts.read_text():
        with hosts.open("a") as output:
            output.write("\n127.0.0.1 " + " ".join(names) + " # pomerium-fixture\n")
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "pomerium-test-backends"], check=False
    )
    if active.returncode:
        subprocess.run(
            [
                "systemd-run",
                "--unit=pomerium-test-backends",
                "/usr/bin/python3",
                __file__,
                "serve",
            ],
            check=True,
        )
    for _ in range(120):
        try:
            status = get(browser(redirects=False), "http://127.0.0.1:28080/readyz")[0]
            if status == 200:
                break
        except OSError:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError("Pomerium did not become ready")

    hits = ROOT / "backend-hits"
    hits.write_text("")
    for host in names[1:]:
        result = get(
            browser(redirects=False),
            "https://" + host + "/",
            {
                "Cookie": "_pomerium=forged",
                "X-Pomerium-Jwt-Assertion": "forged",
                "X-Pomerium-Claim-Email": "fixture@example.invalid",
            },
        )
        assert (
            result[0] == 302
            and urlsplit(result[1]["Location"]).hostname == "pomerium.maxice8.com"
        ), (host, result[0])
    assert not hits.read_text(), "Unauthenticated request reached upstream"
    callback = get(
        browser(redirects=False),
        "https://pomerium.maxice8.com/oauth2/callback?code=forged&state=forged",
    )
    assert callback[0] in [400, 401, 403], callback[0]

    # This is a full synthetic authorization-code exchange; no real user or IdP is used.
    jar = CookieJar()
    opener = browser(jar)
    for host, port in zip(names[1:], PORTS):
        result = get(opener, "https://" + host + "/")
        assert result[0] == 200, (host, result[0], result[2][:200], result[3])
        assert json.loads(result[2]) == {"fixture_backend": port}, (
            host,
            result[2][:200],
        )
    websocket_check(jar)
    serialized = [
        {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "secure": c.secure,
            "expires": c.expires,
        }
        for c in jar
    ]
    # These synthetic cookies let a separate check prove login survives a service restart.
    (ROOT / "cookies.json").write_text(json.dumps(serialized))
    (ROOT / "cookies.json").chmod(0o600)

    pid = subprocess.check_output(
        ["systemctl", "show", "pomerium", "--property=MainPID", "--value"], text=True
    ).strip()
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/" + pid + "/status").read_text().splitlines()
    )
    assert status["Uid"].split()[0] == "62003" and status["Gid"].split()[0] == "62003"
    assert (
        int(status["CapEff"].strip(), 16) == 0 and status["NoNewPrivs"].strip() == "1"
    )
    pids = (
        Path("/sys/fs/cgroup/system.slice/pomerium.service/cgroup.procs")
        .read_text()
        .split()
    )
    for line in subprocess.check_output(["ss", "-lntp"], text=True).splitlines():
        if any("pid=" + process + "," in line for process in pids):
            assert line.split()[3].startswith(("127.0.0.1:", "[::1]:")), line
    assert Path("/var/lib/data/pomerium").stat().st_mode & 0o777 == 0o700
    subprocess.run(
        [
            "sudo",
            "-u",
            "pomerium",
            "test",
            "!",
            "-r",
            "/run/secrets/pomerium-cookie-secret",
        ],
        check=True,
    )
    isolation_check()
    print(
        json.dumps(
            {
                "protected_routes": 5,
                "forged_identity_denied": True,
                "invalid_callback_denied": True,
                "oidc_code_exchange": True,
                "all_authenticated_upstreams": True,
                "authenticated_websocket": True,
                "uid_capabilities_credentials": True,
                "all_listeners_loopback_only": True,
                "actual_cgroup_network_and_bind_controls": True,
            }
        )
    )


def session_check():
    from http.cookiejar import Cookie

    jar = CookieJar()
    for c in json.loads((ROOT / "cookies.json").read_text()):
        jar.set_cookie(
            Cookie(
                0,
                c["name"],
                c["value"],
                None,
                False,
                c["domain"],
                True,
                c["domain"].startswith("."),
                c["path"],
                True,
                c["secure"],
                c["expires"],
                False,
                None,
                None,
                {},
            )
        )
    # Do not follow redirects: a successful response must use the stored session.
    result = get(browser(jar, redirects=False), "https://argus.mashu.maxice8.com/")
    assert result[0] == 200 and json.loads(result[2]) == {"fixture_backend": 8081}, (
        result[0]
    )
    print("PASS: authenticated session survived restart")


if __name__ == "__main__":
    require_vm()
    {"serve": serve, "session": session_check}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", check
    )()
