"""Read-only continuity checks for Mashu: python -m tests.test_vps."""

import argparse
import ipaddress
import json
import subprocess
import time
from urllib.request import ProxyHandler, build_opener

TAILSCALE_HOST = "mashu"
RECOVERY_HOST = "ubuntu@2603:c025:4005:8f7e:0:b837:618:268c"
SSH_OPTIONS = [
    "-T",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "ConnectionAttempts=1",
    "-o",
    "ControlMaster=no",
    "-o",
    "ControlPath=none",
]
IDENTITY = """import json,os,socket
from pathlib import Path
print(json.dumps({'machine':Path('/etc/machine-id').read_text().strip(),
                  'hostname':socket.gethostname(),
                  'address':os.environ['SSH_CONNECTION'].split()[2]}))
"""
HEALTH = """import json,socket,struct,subprocess
units = ['ssh','tailscaled','systemd-resolved','homelab-firewall','unbound','unbound-network',
         'traefik','pomerium','pocket-id','syncthing','forgejo','argus','archisteamfarm',
         'pingvin-share','pingvin-share-frontend','netdata','forgejo-runner','runner-engine','backrest']
subprocess.run(['systemctl','is-active','--quiet',*units],check=True)
failed=subprocess.check_output(['systemctl','--failed','--no-legend','--plain'],text=True).strip()
assert not failed, failed
status=json.loads(subprocess.check_output(['tailscale','status','--json'],text=True))
assert status['BackendState']=='Running' and status['Self']['Online'], 'Tailscale offline'
socket.getaddrinfo('id.maxice8.com',443,type=socket.SOCK_STREAM)
print('PASS host services, Tailscale status and system DNS',flush=True)

def receive(connection,length):
    result=b''
    while len(result)<length:
        chunk=connection.recv(length-len(result))
        assert chunk, 'Truncated DNS response'
        result+=chunk
    return result

query=struct.pack('!6H',0x5281,0x0100,1,0,0,0)+b'\\x0acloudflare\\x03com\\0'+struct.pack('!HH',1,1)
for kind in [socket.SOCK_DGRAM,socket.SOCK_STREAM]:
    with socket.socket(socket.AF_INET,kind) as connection:
        connection.settimeout(10)
        connection.connect(('127.0.0.1',53))
        if kind==socket.SOCK_STREAM:
            connection.sendall(struct.pack('!H',len(query))+query)
            response=receive(connection,struct.unpack('!H',receive(connection,2))[0])
        else:
            connection.send(query)
            response=connection.recv(4096)
    ident,flags,questions,answers,authority,additional=struct.unpack('!6H',response[:12])
    assert ident==0x5281 and flags&15==0 and answers>0, 'Unbound resolution failed'
print('PASS Unbound UDP/TCP resolution',flush=True)

for port,path in [(9080,'/ping'),(28080,'/readyz'),(1411,'/.well-known/openid-configuration'),
                  (8384,'/rest/noauth/health'),(3000,'/api/healthz'),(8081,'/api/v1/healthcheck'),
                  (1242,'/'),(3001,'/'),(3002,'/api/health'),(19999,'/api/v1/info'),(9898,'/')]:
    status=subprocess.check_output(['/usr/bin/curl','--fail','--silent','--show-error',
                    '--location','--noproxy','*','--write-out','%{http_code}',
                    '--output','/dev/null','--retry','60','--retry-max-time','60',
                    '--retry-all-errors','--retry-delay','1','--max-time','5',
                    f'http://127.0.0.1:{port}{path}'],text=True)
    assert status=='200', (port,status)
print('PASS eleven application health endpoints',flush=True)
"""


def ssh(host, options, script, *, privileged=False, timeout=120):
    return subprocess.run(
        [
            "ssh",
            *SSH_OPTIONS,
            *options,
            "--",
            host,
            "sudo -n /usr/bin/python3 -" if privileged else "python3 -",
        ],
        input=script,
        text=True,
        capture_output=True,
        check=True,
        timeout=timeout,
    ).stdout


def check_access(
    target_host,
    tailscale_host,
    recovery_host,
    options=(),
    expected=None,
    require_tailscale=True,
    attempts=1,
):
    failures = []
    paths = [("public SSH", recovery_host)]
    if target_host != recovery_host:
        paths.append(("deployment SSH", target_host))
    if require_tailscale:
        paths.append(("Tailscale SSH", tailscale_host))
    for label, host in paths:
        try:
            for attempt in range(attempts):
                try:
                    identity = json.loads(ssh(host, options, IDENTITY))
                    break
                except subprocess.CalledProcessError as error:
                    if error.returncode != 255 or attempt + 1 == attempts:
                        raise
                    print(f"WAIT fresh {label} connection; retrying", flush=True)
                    time.sleep(2)
            if identity["hostname"] != "mashu":
                raise RuntimeError(f"Unexpected host through {label}")
            if expected is None:
                expected = identity["machine"]
            if identity["machine"] != expected:
                raise RuntimeError(f"Different machine through {label}")
            address = ipaddress.ip_address(identity["address"])
            tailnet = any(
                address in ipaddress.ip_network(network)
                for network in ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]
            )
            if label == "Tailscale SSH" and not tailnet:
                raise RuntimeError("Tailscale check did not use the tailnet address")
            if label == "public SSH" and tailnet:
                raise RuntimeError("Recovery SSH must work independently of Tailscale")
            print(f"PASS fresh {label} connection", flush=True)
        except (
            OSError,
            RuntimeError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
        ) as error:
            detail = (
                error.stderr
                if isinstance(error, subprocess.CalledProcessError)
                else str(error)
            )
            failures.append(f"{label} ({host}): {detail}")
    if failures:
        raise RuntimeError("\n".join(failures))
    return expected


def check_health(target_host, options=()):
    print(ssh(target_host, options, HEALTH, privileged=True), end="", flush=True)
    opener = build_opener(ProxyHandler({}))
    # Cloudflare rejects the default Python user-agent on Pocket ID (error 1010).
    opener.addheaders = [("User-Agent", "mashu-healthcheck/1.0")]
    for url in [
        "https://git.maxice8.com/api/healthz",
        "https://id.maxice8.com/.well-known/openid-configuration",
    ]:
        with opener.open(url, timeout=10) as response:
            assert response.status == 200, (url, response.status)
        print(f"PASS public HTTPS {url}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-host", default=TAILSCALE_HOST)
    parser.add_argument("--tailscale-host", default=TAILSCALE_HOST)
    parser.add_argument("--recovery-host", default=RECOVERY_HOST)
    parser.add_argument("--ssh-option", action="append", default=[])
    args = parser.parse_args()
    check_access(
        args.target_host, args.tailscale_host, args.recovery_host, args.ssh_option
    )
    check_health(args.target_host, args.ssh_option)


if __name__ == "__main__":
    main()
