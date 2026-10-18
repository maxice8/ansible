"""Prepare independent network controls inside the disposable VM, as root."""

import os
import socket
import subprocess
import time
from pathlib import Path

if os.geteuid() != 0 or socket.gethostname() != "mashu-test":
    raise RuntimeError("Run only as root inside the disposable VM")
for directory in ("/var/lib/data/homelab-other", "/opt/homelab-world-writable"):
    Path(directory).mkdir(parents=True, exist_ok=True)
os.chown("/var/lib/data/homelab-other", 62001, 62001)
os.chmod("/var/lib/data/homelab-other", 0o700)
Path("/var/lib/data/homelab-other/marker").write_text("sibling data\n")
Path("/run/homelab-other-secret").write_text("synthetic sibling secret\n")
os.chown("/run/homelab-other-secret", 62001, 62001)
os.chmod("/run/homelab-other-secret", 0o600)
os.chmod("/opt/homelab-world-writable", 0o777)
Path("/tmp/homelab-host-marker").touch()
for address in ("192.0.2.1/32", "169.254.169.254/32", "2001:db8::1/128"):
    subprocess.run(["ip", "address", "replace", address, "dev", "lo"], check=True)
server = Path("/run/homelab-network-control.py")
server.write_text("""import selectors, socket
selector = selectors.DefaultSelector()
for family, address in [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')]:
    for port in (18081, 18082):
        sock = socket.socket(family)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind((address, port))
        sock.listen()
        selector.register(sock, selectors.EVENT_READ)
while True:
    for key, _ in selector.select():
        connection, _ = key.fileobj.accept()
        connection.close()
""")
subprocess.run(["systemctl", "stop", "homelab-network-control.service"], check=False)
subprocess.run(
    ["systemd-run", "--unit=homelab-network-control", "/usr/bin/python3", str(server)],
    check=True,
)
time.sleep(2)
for address in ("127.0.0.1", "::1", "192.0.2.1", "2001:db8::1", "169.254.169.254"):
    for port in (18081, 18082):
        with socket.create_connection((address, port), timeout=3):
            pass
print(
    "All control destinations and both listeners reachable outside the restricted service"
)
