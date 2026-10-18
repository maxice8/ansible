"""Focused native Syncthing health/security check; run as root on the selected host."""

import ipaddress
import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path


def main():
    assert os.geteuid() == 0, "Run as root on the intended deployment target"
    for unit in ("syncthing", "syncthing-network"):
        assert (
            subprocess.check_output(["systemctl", "is-active", unit], text=True).strip()
            == "active"
        )
    base = Path("/var/lib/data/syncthing")
    assert base.stat().st_uid == 977 and base.stat().st_mode & 0o777 == 0o700
    response = urllib.request.urlopen(
        "http://127.0.0.1:8384/rest/noauth/health", timeout=5
    )
    assert json.load(response)["status"] == "OK"
    cgroup = Path("/sys/fs/cgroup/system.slice/syncthing.service/cgroup.procs")
    for pid in cgroup.read_text().split():
        status = dict(
            line.split(":", 1)
            for line in Path(f"/proc/{pid}/status").read_text().splitlines()
        )
        assert status["Uid"].split()[0] == "977" and status["Gid"].split()[0] == "977"
        assert (
            int(status["CapEff"].strip(), 16) == 0
            and status["NoNewPrivs"].strip() == "1"
        )
    # Prove denial against reachable controls, rather than treating a closed port as isolation.
    interfaces = json.loads(
        subprocess.check_output(["ip", "-j", "address", "show"], text=True)
    )
    public_addresses = [
        a["local"]
        for i in interfaces
        for a in i["addr_info"]
        if a["scope"] == "global" and ipaddress.ip_address(a["local"]).is_global
    ]
    denied = [("127.0.0.1", 22), ("169.254.169.254", 80)] + [
        (a, 22) for a in public_addresses
    ]
    for address, port in denied:
        socket.create_connection((address, port), timeout=3).close()
    code = """from pathlib import Path
import errno,os,socket
Path('/sys/fs/cgroup/system.slice/syncthing.service/cgroup.procs').write_text(str(os.getpid()))
os.setgroups([]);os.setgid(977);os.setuid(977)
for address,port,expected in [('127.0.0.1',8384,True),('127.0.0.53',53,True)]+[(a,p,False) for a,p in __DENIED__]:
 try:socket.create_connection((address,port),timeout=3).close();allowed=True
 except OSError:allowed=False
 assert allowed==expected,(address,port,allowed)
for family,address in [(socket.AF_INET,'127.0.0.1'),(socket.AF_INET6,'::1')]:
 with socket.socket(family) as s:
  try:s.bind((address,18085))
  except OSError as e:assert e.errno in (errno.EACCES,errno.EPERM)
  else:raise AssertionError('Unapproved named bind succeeded')
""".replace("__DENIED__", repr(denied))
    subprocess.run(["/usr/bin/python3", "-c", code], check=True)
    print(
        "Syncthing health, private state, process identity/capabilities and live cgroup network/bind checks passed"
    )


if __name__ == "__main__":
    main()
