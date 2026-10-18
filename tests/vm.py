"""On-demand NixOS ARM builder/test guest, with persistent cache and no host binfmt."""

import base64
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

DEFAULT_DIRECTORY = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "mashu-nix/vm"
)


class NixVM:
    """Serialize sessions and shut down only the guest started by this invocation."""

    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.environment = os.environ.copy()
        self.lock = None
        self.process = None
        self.started = False
        self.image = None

    def __enter__(self):
        return self

    def acquire(self):
        if self.lock is None:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.lock = (self.directory / "session.lock").open("a")
            print(f"Waiting for ARM VM session: {self.directory}", flush=True)
            fcntl.flock(self.lock, fcntl.LOCK_EX)

    def __exit__(self, error_type, _error, _traceback):
        try:
            if self.started:
                try:
                    self.stop()
                except (OSError, RuntimeError, subprocess.SubprocessError) as error:
                    if error_type is None:
                        raise
                    print(
                        f"VM cleanup also failed: {error}; retained at {self.directory}",
                        file=sys.stderr,
                    )
        finally:
            if self.lock is not None:
                self.lock.close()
                self.lock = None

    def pid(self):
        """Validate the exact emulator/disk/SSH mapping before controlling a process."""
        file = self.directory / "running.json"
        if not file.exists():
            return None
        state = json.loads(file.read_text())
        proc = Path(f"/proc/{state['pid']}")
        try:
            command = (proc / "cmdline").read_bytes().split(b"\0")
            status = (proc / "stat").read_text().split(") ", 1)[1].split()[0]
        except FileNotFoundError:
            file.unlink(missing_ok=True)
            return None
        if status == "Z":
            file.unlink(missing_ok=True)
            return None
        if (
            b"qemu-system-aarch64" not in command[0]
            or not any(f"file={state['disk']},".encode() in arg for arg in command)
            or not any(
                f"hostfwd=tcp:127.0.0.1:{state['port']}-:22".encode() in arg
                for arg in command
            )
        ):
            raise RuntimeError(
                "VM PID does not match its recorded emulator, disk and SSH port"
            )
        return state["pid"]

    def ssh(self, command, **kwargs):
        text = (self.directory / "ssh_config").read_text()
        if "HostName 127.0.0.1\n" not in text or "User builder\n" not in text:
            raise RuntimeError("Refusing SSH outside the local builder guest")
        state = json.loads((self.directory / "running.json").read_text())
        port = next(
            line.split()[1]
            for line in text.splitlines()
            if line.strip().startswith("Port ")
        )
        if port != str(state["port"]):
            raise RuntimeError("SSH configuration does not match the managed VM port")
        return subprocess.run(
            ["ssh", "-F", str(self.directory / "ssh_config"), "vm", command],
            check=True,
            text=True,
            env=self.environment,
            **kwargs,
        )

    def prepare(self, image: str):
        self.acquire()
        running = self.pid()
        if running is not None:
            state = json.loads((self.directory / "running.json").read_text())
            if state["image"] == image:
                self.image = image
                return
            if not self.started:
                raise RuntimeError(
                    "Another VM image is running; stop it before changing images"
                )
            self.stop()
        work = self.directory
        key = work / "id_ed25519"
        if not key.exists():
            subprocess.run(
                [
                    "ssh-keygen",
                    "-q",
                    "-t",
                    "ed25519",
                    "-N",
                    "",
                    "-C",
                    "mashu-test-vm",
                    "-f",
                    str(key),
                ],
                check=True,
            )
        keys = work / "keys"
        keys.mkdir(exist_ok=True, mode=0o700)
        (keys / "authorized_keys").write_bytes(key.with_suffix(".pub").read_bytes())
        (keys / "authorized_keys").chmod(0o644)
        # A distinct writable disk per image avoids stale Nix DB references to a
        # previous image's read-only store; each disk survives repeated sessions.
        disk = work / ("disk-" + Path(image).name.split("-", 1)[0] + ".qcow2")

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (work / "ssh_config").write_text(
            "Host vm\n  HostName 127.0.0.1\n  User builder\n"
            f"  Port {port}\n  IdentityFile {key}\n"
            f"  UserKnownHostsFile {work / 'known_hosts'}\n"
            "  StrictHostKeyChecking accept-new\n  BatchMode yes\n"
            "  ConnectTimeout 5\n  ServerAliveInterval 5\n  ServerAliveCountMax 6\n"
            f"  ControlMaster auto\n  ControlPersist 60\n  ControlPath {work / 'ssh-control'}\n"
        )
        environment = self.environment | {
            "NIX_DISK_IMAGE": str(disk),
            "VM_KEY_DIRECTORY": str(keys),
            "VM_SSH_PORT": str(port),
            # The NixOS runner otherwise leaks a new store image in /tmp per boot.
            "TMPDIR": str(work / "runtime"),
            "USE_TMPDIR": "1",
        }
        (work / "runtime").mkdir(exist_ok=True, mode=0o700)
        runner = Path(image) / "bin/run-mashu-test-vm"
        with (work / "console.log").open("ab") as log:
            self.process = subprocess.Popen(
                [str(runner)],
                cwd=work,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        self.started = True
        self.image = image
        state = {
            "pid": self.process.pid,
            "disk": str(disk),
            "port": port,
            "image": image,
        }
        (work / "running.json").write_text(json.dumps(state))
        print(
            f"Starting minimal NixOS ARM VM; console: {work / 'console.log'}",
            flush=True,
        )
        for _ in range(180):
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"VM exited during startup; inspect {work / 'console.log'}"
                )
            try:
                self.ssh("true", capture_output=True)
                break
            except subprocess.CalledProcessError:
                time.sleep(3)
        else:
            raise TimeoutError(
                f"VM SSH did not become ready; inspect {work / 'console.log'}"
            )
        self.pid()
        if self.ssh("hostname", capture_output=True).stdout.strip() != "mashu-test":
            raise RuntimeError("Refusing a non-test host")
        if self.ssh("uname -m", capture_output=True).stdout.strip() != "aarch64":
            raise RuntimeError("Builder guest must be ARM64")
        self.ssh("nix store info")

    def builder(self):
        state = json.loads((self.directory / "running.json").read_text())
        self.pid()
        key = self.ssh(
            "cat /etc/ssh/ssh_host_ed25519_key.pub", capture_output=True
        ).stdout.strip()
        query = urlencode(
            {
                "ssh-key": str(self.directory / "id_ed25519"),
                "base64-ssh-public-host-key": base64.b64encode(key.encode()).decode(),
            }
        )
        return f"ssh://builder@127.0.0.1:{state['port']}?{query} aarch64-linux - 2 1"

    def stop(self):
        self.acquire()
        if self.pid() is None:
            self.started = False
            if (self.directory / "runtime").exists():
                shutil.rmtree(self.directory / "runtime")
            return
        # An interrupted startup may reach cleanup before sshd is ready.
        for _ in range(40):
            try:
                hostname = self.ssh("hostname", capture_output=True).stdout.strip()
                break
            except subprocess.CalledProcessError:
                time.sleep(3)
        else:
            raise RuntimeError("Guest SSH unavailable for normal poweroff; VM retained")
        if hostname != "mashu-test":
            raise RuntimeError("Refusing to stop a non-test host")
        print("Stopping NixOS ARM VM; disk and Nix cache retained", flush=True)
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "ControlMaster=no",
                "-o",
                "ControlPath=none",
                "-F",
                str(self.directory / "ssh_config"),
                "vm",
                "sudo systemctl poweroff",
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=40,
        )
        if result.returncode not in (0, 255):
            raise RuntimeError(
                result.stderr.strip() or "Guest rejected normal poweroff"
            )
        for _ in range(240):
            if self.process is not None:
                self.process.poll()
            if self.pid() is None:
                self.started = False
                if (self.directory / "runtime").exists():
                    shutil.rmtree(self.directory / "runtime")
                print("ARM VM stopped", flush=True)
                return
            time.sleep(0.5)
        raise RuntimeError(
            "Guest shutdown still pending; no emulator signal or inhibitor override used"
        )
