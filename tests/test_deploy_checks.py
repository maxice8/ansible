"""Check deployment gates without changing the host."""

import io
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import deploy_health as remote
from scripts.checklist import Checklist
from tests import test_vps as checks


class Response(io.BytesIO):
    def __init__(self, status, location="", body=b""):
        super().__init__(body)
        self.status = status
        self.headers = {"Location": location}


class RouteTests(unittest.TestCase):
    def test_rejects_authentication_bypass_and_wrong_redirects(self):
        for status, location in [
            (200, ""),
            (503, ""),
            (302, "https://wrong.example/.pomerium/sign_in?state=private"),
            (302, "http://pomerium.maxice8.com/.pomerium/sign_in"),
        ]:
            opener = SimpleNamespace(
                open=unittest.mock.Mock(return_value=Response(status, location))
            )
            with (
                self.subTest(status=status, location=location),
                self.assertRaises(AssertionError) as error,
            ):
                checks.check_redirect(
                    opener,
                    "https://argus.mashu.maxice8.com/",
                    ("https", "pomerium.maxice8.com", "/.pomerium/sign_in"),
                )
            self.assertNotIn("state=private", str(error.exception))

    def test_accepts_urllib_redirect_errors_without_following_them(self):
        error = HTTPError(
            "https://argus.mashu.maxice8.com/",
            302,
            "Found",
            {
                "Location": "https://pomerium.maxice8.com/.pomerium/sign_in?state=private"
            },
            io.BytesIO(),
        )
        opener = SimpleNamespace(open=unittest.mock.Mock(side_effect=error))
        checks.check_redirect(
            opener, error.url, ("https", "pomerium.maxice8.com", "/.pomerium/sign_in")
        )
        self.assertIsNone(
            checks.NoRedirect().redirect_request(None, None, 302, None, None, None)
        )

    def check_routes(self, refs, api_body=b"OK"):
        visited = []

        def open_url(url, **kwargs):
            visited.append(url)
            if url == "https://pomerium.maxice8.com/":
                return Response(302, "/.pomerium/")
            if url == "https://pomerium.maxice8.com/.pomerium/":
                return Response(302, "https://id.maxice8.com/authorize?state=private")
            if any(
                url.startswith(f"https://{host}.mashu.")
                for host in ["argus", "asf", "backrest", "netdata", "syncthing"]
            ):
                return Response(
                    302, "https://pomerium.maxice8.com/.pomerium/sign_in?state=private"
                )
            return Response(200, body=api_body)

        with (
            patch.object(checks, "ssh"),
            patch.object(
                checks, "build_opener", return_value=SimpleNamespace(open=open_url)
            ),
            patch.object(
                checks.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0, refs, ""),
            ) as git,
        ):
            checks.check_health("unused", report=Checklist(io.StringIO()))
        self.assertEqual(len(visited), 11)
        self.assertIn("https://share.mashu.maxice8.com/api/health", visited)
        command = git.call_args.args[0]
        self.assertIn("ssh://git@git.maxice8.com:23/max/ansible.git", command)
        self.assertIn("BatchMode=yes", git.call_args.kwargs["env"]["GIT_SSH_COMMAND"])

    def test_all_public_routes_and_git_head_with_extra_refs(self):
        self.check_routes(
            "a" * 40 + "\tHEAD\n" + "b" * 40 + "\trefs/remotes/other/HEAD\n"
        )

    def test_nested_head_does_not_replace_repository_head(self):
        with self.assertRaisesRegex(AssertionError, "No repository HEAD"):
            self.check_routes("b" * 40 + "\trefs/remotes/other/HEAD\n")

    def test_share_api_rejects_a_frontend_fallback(self):
        with self.assertRaisesRegex(AssertionError, "did not reach the backend"):
            self.check_routes("a" * 40 + "\tHEAD\n", api_body=b"<html>frontend</html>")


class RemoteChecksTests(unittest.TestCase):
    def test_storage_rejects_low_bytes_or_inodes(self):
        for available, inodes, healthy in [
            (1024**3, 10000, True),
            (1024**3 - 1, 10000, False),
            (1024**3, 9999, False),
        ]:
            with (
                self.subTest(available=available, inodes=inodes),
                patch.object(
                    remote.os,
                    "statvfs",
                    return_value=SimpleNamespace(
                        f_bavail=available, f_frsize=1, f_favail=inodes
                    ),
                ),
                patch("builtins.print"),
            ):
                if healthy:
                    remote.storage()
                else:
                    with self.assertRaises(AssertionError):
                        remote.storage()

    def test_application_probe_uses_service_mount_and_uid(self):
        with (
            patch.object(remote.subprocess, "check_output", return_value="123"),
            patch.object(
                remote.pwd,
                "getpwnam",
                return_value=SimpleNamespace(pw_uid=5012, pw_gid=5012),
            ),
            patch.object(remote.subprocess, "run") as run,
            patch("builtins.print"),
        ):
            remote.application_dns()
        command = run.call_args.args[0]
        self.assertEqual(
            command[:5], ["/usr/bin/nsenter", "--target", "123", "--mount", "--"]
        )
        self.assertEqual(command[command.index("--reuid") + 1], "5012")
        self.assertIn("--clear-groups", command)
        self.assertEqual(run.call_args.kwargs["timeout"], 15)

    def test_runner_probe_always_removes_its_container(self):
        for failure in [None, "create", "start", "wait", "dns", "cleanup"]:
            calls = []

            def api(method, path, data=None, failure=failure, calls=calls):
                calls.append((method, path, data))
                if path == "/images/json":
                    return [
                        {
                            "Id": "cached-image",
                            "RepoTags": ["docker.io/library/alpine:3.22"],
                        }
                    ]
                if path.startswith("/containers/create"):
                    self.assertEqual(data["Image"], "cached-image")
                    self.assertNotIn("Binds", data["HostConfig"])
                    if failure == "create":
                        raise subprocess.TimeoutExpired("create", 15)
                    return {"Id": "probe"}
                if failure in ("start", "wait") and path.endswith("/" + failure):
                    raise RuntimeError("probe failed")
                if method == "DELETE" and failure == "cleanup":
                    raise RuntimeError("cleanup failed")
                if path.endswith("/wait"):
                    return {"StatusCode": 1 if failure == "dns" else 0}

            with (
                self.subTest(failure=failure),
                patch.object(remote, "engine_api", side_effect=api),
                patch.object(
                    remote.uuid, "uuid4", return_value=SimpleNamespace(hex="probe")
                ),
                patch("builtins.print"),
            ):
                if failure:
                    with self.assertRaises(
                        (RuntimeError, AssertionError, subprocess.TimeoutExpired)
                    ):
                        remote.runner_dns()
                else:
                    remote.runner_dns()
            self.assertEqual(
                calls[-1][:2],
                ("DELETE", "/containers/mashu-deploy-dns-probe?force=true&v=true"),
            )
            self.assertFalse(any("pull" in path for _, path, _ in calls))

    def test_runner_api_checks_http_errors_and_accepts_missing_cleanup(self):
        for method, reply, healthy in [
            ("POST", "{}\n201", True),
            ("POST", "{}\n500", False),
            ("DELETE", "{}\n404", True),
        ]:
            with (
                self.subTest(method=method, reply=reply),
                patch.object(
                    remote.subprocess, "check_output", return_value=reply
                ) as output,
            ):
                if healthy:
                    remote.engine_api(method, "/containers/probe")
                else:
                    with self.assertRaisesRegex(AssertionError, "HTTP 500"):
                        remote.engine_api(method, "/containers/probe")
                self.assertEqual(output.call_args.kwargs["timeout"], 15)

    def test_runner_probe_does_not_pull_a_missing_image(self):
        with (
            patch.object(remote, "engine_api", return_value=[]) as api,
            patch("builtins.print"),
            self.assertRaisesRegex(AssertionError, "No cached Alpine"),
        ):
            remote.runner_dns()
        api.assert_called_once_with("GET", "/images/json")

    def test_service_snapshot_rejects_missing_or_inactive_units(self):
        for active, count in [
            ("active", len(remote.UNITS)),
            ("inactive", len(remote.UNITS)),
            ("active", 1),
        ]:
            output = "\n\n".join(
                f"Id={unit}.service\nActiveState={active}\nNRestarts=0\nMainPID=123"
                for unit in remote.UNITS[:count]
            )
            with (
                self.subTest(active=active, count=count),
                patch.object(remote.subprocess, "check_output", return_value=output),
            ):
                if active == "active" and count == len(remote.UNITS):
                    self.assertEqual(len(remote.service_state()), count)
                else:
                    with self.assertRaises(AssertionError):
                        remote.service_state()


class StabilityTests(unittest.TestCase):
    def test_readiness_and_restart_failures_block_stability(self):
        for failure in [None, "health", "restart", "pid"]:
            before = {"forgejo.service": [0, 123]}
            after = {
                "forgejo.service": [
                    1 if failure == "restart" else 0,
                    456 if failure == "pid" else 123,
                ]
            }
            stream = io.StringIO()
            with (
                self.subTest(failure=failure),
                patch.object(
                    checks, "ssh", side_effect=[json.dumps(before), json.dumps(after)]
                ),
                patch.object(
                    checks,
                    "check_health",
                    side_effect=RuntimeError("readiness lost")
                    if failure == "health"
                    else None,
                ) as health,
                patch.object(checks.time, "sleep") as sleep,
                patch.object(checks.time, "monotonic", return_value=100),
            ):
                if failure:
                    with self.assertRaises((AssertionError, RuntimeError)):
                        checks.check_stability("unused", report=Checklist(stream))
                else:
                    checks.check_stability("unused", report=Checklist(stream))
                    self.assertEqual(
                        [call.args[0] for call in sleep.call_args_list], [5, 10, 15]
                    )
                    self.assertEqual(health.call_count, 3)
                    self.assertTrue(
                        all(
                            not call.kwargs["probe_runner"]
                            and not call.kwargs["probe_git"]
                            for call in health.call_args_list
                        )
                    )
            if failure:
                self.assertIn("✗", stream.getvalue())
                self.assertNotIn(
                    "✓ No new automatic service restarts", stream.getvalue()
                )


if __name__ == "__main__":
    unittest.main()
