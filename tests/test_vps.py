"""Read-only continuity checks for Mashu: python -m tests.test_vps."""

import argparse
import ipaddress
import json
import os
import selectors
import subprocess
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

from scripts.checklist import Checklist

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
HEALTH = """import json,socket,struct,subprocess,time
from concurrent.futures import ThreadPoolExecutor, as_completed
units = ['ssh','tailscaled','systemd-resolved','homelab-firewall','unbound','unbound-network',
         'traefik','pomerium','pocket-id','syncthing','forgejo','argus','archisteamfarm',
         'pingvin-share','pingvin-share-frontend','netdata','forgejo-runner','runner-engine','backrest']
print('GROUP\tHost',flush=True)
print('CHECK\tManaged services',flush=True)
for unit in units:
    subprocess.run(['systemctl','is-active','--quiet',unit],check=True)
failed=subprocess.check_output(['systemctl','--failed','--no-legend','--plain'],text=True).strip()
assert not failed, failed
print('PASS\tManaged services',flush=True)
print('CHECK\tTailscale status',flush=True)
status=json.loads(subprocess.check_output(['tailscale','status','--json'],text=True))
assert status['BackendState']=='Running' and status['Self']['Online'], 'Tailscale offline'
print('PASS\tTailscale status',flush=True)
print('GROUP\tDNS',flush=True)
print('CHECK\tSystem resolution',flush=True)
socket.getaddrinfo('id.maxice8.com',443,type=socket.SOCK_STREAM)
print('PASS\tSystem resolution',flush=True)

def receive(connection,length):
    result=b''
    while len(result)<length:
        chunk=connection.recv(length-len(result))
        assert chunk, 'Truncated DNS response'
        result+=chunk
    return result

query=struct.pack('!6H',0x5281,0x0100,1,0,0,0)+b'\\x0acloudflare\\x03com\\0'+struct.pack('!HH',1,1)
for kind in [socket.SOCK_DGRAM,socket.SOCK_STREAM]:
    label='Unbound UDP' if kind==socket.SOCK_DGRAM else 'Unbound TCP'
    print('CHECK\t'+label,flush=True)
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
    print('PASS\t'+label,flush=True)

endpoints = [('Traefik',9080,'/ping'),('Pomerium',28080,'/readyz'),
             ('Pocket ID',1411,'/.well-known/openid-configuration'),
             ('Syncthing',8384,'/rest/noauth/health'),('Forgejo',3000,'/api/healthz'),
             ('Argus',8081,'/api/v1/healthcheck'),('ArchiSteamFarm',1242,'/'),
             ('Pingvin Share frontend',3001,'/'),('Pingvin Share API',3002,'/api/health'),
             ('Netdata',19999,'/api/v1/info'),('Backrest',9898,'/')]
print('GROUP\tApplications',flush=True)
deadline = time.monotonic() + 65
def check_endpoint(endpoint):
    name,port,path = endpoint
    status=subprocess.check_output(['/usr/bin/curl','--fail','--silent','--show-error',
                    '--location','--noproxy','*','--write-out','%{http_code}',
                    '--output','/dev/null','--retry','60','--retry-max-time','60',
                    '--retry-all-errors','--retry-delay','1','--max-time','5',
                    f'http://127.0.0.1:{port}{path}'],text=True,
                    timeout=max(0.001,deadline-time.monotonic()))
    assert status=='200', (port,status)
with ThreadPoolExecutor(max_workers=len(endpoints)) as pool:
    pending={pool.submit(check_endpoint,endpoint):endpoint[0] for endpoint in endpoints}
    for future in as_completed(pending):
        print('CHECK\t'+pending[future],flush=True)
        future.result()
        print('PASS\t'+pending[future],flush=True)
"""


def ssh(host, options, script, *, privileged=False, timeout=120, on_line=None):
    command = [
        "ssh",
        *SSH_OPTIONS,
        *options,
        "--",
        host,
        "sudo -n /usr/bin/python3 -" if privileged else "python3 -",
    ]
    if on_line is None:
        return subprocess.run(
            command,
            input=script,
            text=True,
            capture_output=True,
            check=True,
            timeout=timeout,
        ).stdout
    with tempfile.TemporaryFile() as remote_input:
        remote_input.write(script.encode())
        remote_input.seek(0)
        # Keep stderr separate so diagnostics cannot become checklist events.
        with (
            tempfile.TemporaryFile() as errors,
            subprocess.Popen(
                command, stdin=remote_input, stdout=subprocess.PIPE, stderr=errors
            ) as process,
            selectors.DefaultSelector() as selector,
        ):
            output = b""
            pending = b""
            deadline = time.monotonic() + timeout
            try:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(command, timeout)
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        selector.unregister(process.stdout)
                        break
                    output += chunk
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        on_line(line.decode(errors="replace"))
                if pending:
                    on_line(pending.decode(errors="replace"))
                process.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException as error:
                process.kill()
                process.wait()
                if isinstance(error, subprocess.TimeoutExpired):
                    errors.seek(0)
                    error.output = output.decode(errors="replace")
                    error.stderr = errors.read().decode(errors="replace")
                raise
            errors.seek(0)
            if process.returncode:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    command,
                    output.decode(errors="replace"),
                    errors.read().decode(errors="replace"),
                )
            return output.decode(errors="replace")


def check_access(
    target_host,
    tailscale_host,
    recovery_host,
    options=(),
    expected=None,
    require_tailscale=True,
    attempts=1,
    report=None,
):
    report = report or Checklist()
    report.group("SSH")
    failures = []
    paths = [("public SSH", recovery_host)]
    if target_host != recovery_host:
        paths.append(("deployment SSH", target_host))
    if require_tailscale:
        paths.append(("Tailscale SSH", tailscale_host))
    for label, host in paths:
        report.start(
            {
                "public SSH": "Public connection",
                "deployment SSH": "Deployment connection",
                "Tailscale SSH": "Tailscale connection",
            }[label],
            child=True,
        )
        try:
            for attempt in range(attempts):
                try:
                    identity = json.loads(ssh(host, options, IDENTITY))
                    break
                except subprocess.CalledProcessError as error:
                    if error.returncode != 255 or attempt + 1 == attempts:
                        raise
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
            report.finish()
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
            report.finish(False)
            failures.append(f"{label} ({host}): {detail}")
    if failures:
        raise RuntimeError("\n".join(failures))
    return expected


def check_health(target_host, options=(), report=None):
    report = report or Checklist()
    try:
        ssh(target_host, options, HEALTH, privileged=True, on_line=report.feed)
    except BaseException:
        report.fail_active()
        raise
    opener = build_opener(ProxyHandler({}))
    # Cloudflare rejects the default Python user-agent on Pocket ID (error 1010).
    opener.addheaders = [("User-Agent", "mashu-healthcheck/1.0")]
    report.group("Public HTTPS")
    for label, url in [
        ("git.maxice8.com · health", "https://git.maxice8.com/api/healthz"),
        (
            "id.maxice8.com · OpenID configuration",
            "https://id.maxice8.com/.well-known/openid-configuration",
        ),
    ]:
        with report.step(label, child=True), opener.open(url, timeout=10) as response:
            assert response.status == 200, (url, response.status)


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
