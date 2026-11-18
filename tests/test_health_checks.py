"""Check readiness failures without connecting to the VPS."""

import json
import struct
import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

from scripts import deploy_health as remote


class HealthTests(unittest.TestCase):
    def test_inactive_runner_fails_even_when_other_units_are_active(self):
        def check_unit(command, **kwargs):
            if command[-1] == "forgejo-runner":
                raise subprocess.CalledProcessError(3, command)

        with (
            patch("subprocess.run", side_effect=check_unit) as run,
            patch("subprocess.check_output") as output,
            patch("time.sleep") as sleep,
            self.assertRaises(subprocess.CalledProcessError),
        ):
            remote.health()
        self.assertEqual(run.call_count, (remote.SERVICE_WAIT_SECONDS + 1) * 17)
        self.assertEqual(sleep.call_count, remote.SERVICE_WAIT_SECONDS)
        output.assert_not_called()

    def test_restarting_runner_recovers(self):
        self.check_endpoints(runner_restart_seconds=37)

    def test_http_checks_share_a_deadline_and_run_concurrently(self):
        self.check_endpoints()

    def test_http_failure_rejects_readiness(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.check_endpoints(failure=subprocess.CalledProcessError)

    def test_http_deadline_rejects_readiness(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.check_endpoints(failure=subprocess.TimeoutExpired)

    def check_endpoints(self, failure=None, runner_restart_seconds=0):
        barrier = threading.Barrier(11)
        response = struct.pack("!6H", 0x5281, 0x8180, 1, 1, 0, 0)
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = [
            response,
            struct.pack("!H", len(response)),
            response,
        ]
        runner_attempts = 0

        def check_unit(command, **kwargs):
            nonlocal runner_attempts
            if command[-1] == "forgejo-runner":
                runner_attempts += 1
                if runner_attempts <= runner_restart_seconds:
                    raise subprocess.CalledProcessError(3, command)

        def output(command, **kwargs):
            if command[0] == "systemctl":
                return ""
            if command[0] == "tailscale":
                return json.dumps({"BackendState": "Running", "Self": {"Online": True}})
            self.assertEqual(kwargs["timeout"], 55)
            barrier.wait(timeout=5)
            if failure and command[-1].endswith(":9080/ping"):
                if failure is subprocess.TimeoutExpired:
                    raise failure(command, kwargs["timeout"])
                raise failure(7, command)
            return "200"

        with (
            patch("subprocess.run", side_effect=check_unit),
            patch("time.sleep") as sleep,
            patch("subprocess.check_output", side_effect=output),
            patch("socket.getaddrinfo"),
            patch("socket.socket", return_value=connection),
            patch("time.monotonic", side_effect=[100] + [110] * 11),
            patch("builtins.print") as progress,
            patch.object(remote, "application_dns"),
            patch.object(remote, "runner_dns"),
        ):
            remote.health()
        if runner_restart_seconds:
            self.assertEqual(runner_attempts, runner_restart_seconds + 1)
            self.assertEqual(sleep.call_count, runner_restart_seconds)
        events = [call.args[0] for call in progress.call_args_list]
        self.assertIn("PASS\tSystem resolution", events)
        self.assertIn("PASS\tUnbound UDP", events)
        self.assertIn("PASS\tUnbound TCP", events)
        applications = events[events.index("GROUP\tApplications") + 1 :]
        self.assertEqual(sum(event.startswith("PASS\t") for event in applications), 11)
        self.assertIn("PASS\tForgejo", applications)
        self.assertIn("PASS\tPingvin Share frontend", applications)


if __name__ == "__main__":
    unittest.main()
