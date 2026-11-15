"""Check deployment access gates and rollback cancellation."""

import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import deploy
from scripts import deploy_guard as guard


class GuardTests(unittest.TestCase):
    def test_clear_without_guard_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with (
                patch.object(guard, "STATE", base / "state"),
                patch.object(guard, "ROOT", base / "gcroot"),
                patch("builtins.open", unittest.mock.mock_open()),
                patch.object(guard.fcntl, "flock"),
                patch.object(
                    guard,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, "inactive"),
                ),
            ):
                guard.main("clear")
                (base / "gcroot").symlink_to(base / "missing")
                with self.assertRaises(RuntimeError):
                    guard.main("clear")
                self.assertTrue((base / "gcroot").is_symlink())

    def test_remote_guard_omits_absent_profile(self):
        for action, profile in (("clear", None), ("arm", "/candidate")):
            with self.subTest(action=action), patch.object(deploy, "ssh") as ssh:
                deploy.deployment_guard("host", [], action, profile)
                script = ssh.call_args.args[2]
                with patch.object(subprocess, "run") as run:
                    exec(script, {})  # noqa: S102 - Run the generated SSH script with subprocess mocked.
                arguments = run.call_args.args[0]
                self.assertEqual(
                    arguments[2:], [action] if profile is None else [action, profile]
                )
                self.assertTrue(all(isinstance(arg, str) for arg in arguments))

    def test_clear_only_removes_an_inactive_restored_guard(self):
        for status, started, restored in (
            ("active", True, True),
            ("activating", True, True),
            ("inactive", False, True),
            ("inactive", True, False),
            ("inactive", True, True),
        ):
            with (
                self.subTest(status=status, started=started, restored=restored),
                tempfile.TemporaryDirectory() as directory,
            ):
                base = Path(directory)
                previous = base / "previous"
                previous.mkdir()
                state = base / "state"
                state.mkdir()
                if started:
                    (state / "rollback-started").touch()
                root = base / "gcroot"
                root.symlink_to(previous)
                current = base / "current"
                current.symlink_to(previous if restored else base)
                with (
                    patch.object(guard, "STATE", state),
                    patch.object(guard, "ROOT", root),
                    patch.object(guard, "CURRENT", current),
                    patch("builtins.open", unittest.mock.mock_open()),
                    patch.object(guard.fcntl, "flock"),
                    patch.object(
                        guard,
                        "run",
                        return_value=subprocess.CompletedProcess([], 0, status),
                    ),
                ):
                    if status == "inactive" and started and restored:
                        guard.main("clear")
                        self.assertFalse(state.exists())
                        self.assertFalse(root.is_symlink())
                    else:
                        with self.assertRaises(RuntimeError):
                            guard.main("clear")
                        self.assertTrue(state.exists())
                        self.assertTrue(root.is_symlink())

    def test_clear_checks_health_without_building(self):
        for healthy in (True, False):
            with (
                self.subTest(healthy=healthy),
                patch("sys.argv", ["deploy.py", "clear-rollback"]),
                patch.object(deploy, "check_access"),
                patch.object(
                    deploy,
                    "check_health",
                    side_effect=None if healthy else RuntimeError("unhealthy"),
                ),
                patch.object(deploy, "snapshot") as snapshot,
                patch.object(deploy, "deployment_guard", return_value="") as gate,
            ):
                self.assertEqual(deploy.main(), 0 if healthy else 1)
                snapshot.assert_not_called()
                if healthy:
                    self.assertEqual(gate.call_args.args[2:], ("clear", None))
                else:
                    gate.assert_not_called()

    def test_firewall_requires_ssh_before_blocking_rules(self):
        policy = (deploy.ROOT / "services/host-firewall.nft").read_text()
        guard.check_firewall(policy)
        for changed in (
            policy.replace("22, 80", "80"),
            policy.replace("ct state invalid drop", "tcp dport 22 drop"),
            policy.replace("ct state invalid drop", "jump deny_ssh"),
        ):
            with self.subTest(policy=changed), self.assertRaises(RuntimeError):
                guard.check_firewall(changed)

    def test_arm_and_disarm_preserve_previous_profile_until_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            previous = base / "previous"
            (previous / "bin").mkdir(parents=True)
            (previous / "bin/activate").touch()
            current = base / "current"
            current.symlink_to(previous)
            state = base / "state"
            root = base / "gcroot"
            with (
                patch.object(guard, "STATE", state),
                patch.object(guard, "ROOT", root),
                patch.object(guard, "CURRENT", current),
                patch("builtins.open", unittest.mock.mock_open()),
                patch.object(guard.fcntl, "flock"),
                patch.object(guard, "preflight") as preflight,
                patch.object(guard, "run") as run,
            ):

                def result(*args, **kwargs):
                    if args[0] == "busctl":
                        value = f"t {int((time.monotonic() + 1800) * 1000000)}"
                    elif "--property=SubState" in args:
                        value = "ActiveState=active\nSubState=waiting\n"
                    else:
                        value = "inactive\n"
                    return subprocess.CompletedProcess(args, 0, value)

                run.side_effect = result
                guard.main("arm", "/candidate")
                preflight.assert_called_once_with("/candidate")
                self.assertEqual(root.resolve(), previous)
                self.assertTrue(
                    any("--on-active=30m" in call.args for call in run.call_args_list)
                )
                with self.assertRaisesRegex(RuntimeError, "previous deployment"):
                    guard.main("arm", "/candidate")
                with self.assertRaisesRegex(RuntimeError, "no longer active"):
                    guard.main("disarm", "/candidate")
                self.assertTrue(root.exists())
                current.unlink()
                current.symlink_to("/candidate")
                guard.main("disarm", "/candidate")
                self.assertFalse(root.is_symlink())
                self.assertFalse(state.exists())
                run.assert_any_call("systemctl", "stop", guard.UNIT + ".timer")

    def test_invalid_timer_keeps_recovery_state(self):
        for status, trigger in [
            ("ActiveState=inactive\nSubState=dead", "t 1900000000"),
            ("ActiveState=active\nSubState=waiting", "t 99000000"),
            ("ActiveState=active\nSubState=waiting", "t 2000000000"),
            ("ActiveState=active\nSubState=waiting", "invalid"),
        ]:
            with (
                self.subTest(status=status, trigger=trigger),
                tempfile.TemporaryDirectory() as directory,
            ):
                base = Path(directory)
                previous = base / "previous"
                (previous / "bin").mkdir(parents=True)
                (previous / "bin/activate").touch()
                current = base / "current"
                current.symlink_to(previous)
                state, root = base / "state", base / "root"

                def run(*args, status=status, trigger=trigger, **kwargs):
                    return subprocess.CompletedProcess(
                        args, 0, trigger if args[0] == "busctl" else status
                    )

                with (
                    patch.object(guard, "STATE", state),
                    patch.object(guard, "ROOT", root),
                    patch.object(guard, "CURRENT", current),
                    patch("builtins.open", unittest.mock.mock_open()),
                    patch.object(guard.fcntl, "flock"),
                    patch.object(guard, "preflight"),
                    patch.object(guard, "run", side_effect=run),
                    patch.object(guard.time, "monotonic", return_value=100),
                    patch("builtins.print"),
                    self.assertRaises(AssertionError),
                ):
                    guard.main("arm", "/candidate")
                self.assertEqual(root.resolve(), previous)
                self.assertEqual((state / "candidate").read_text(), "/candidate")

    def test_disarm_does_not_remove_state_while_timer_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            state.mkdir()
            (state / "candidate").write_text("/candidate")
            root = Path(directory) / "root"
            root.symlink_to("/previous")
            with (
                patch.object(guard, "STATE", state),
                patch.object(guard, "ROOT", root),
                patch.object(guard, "CURRENT", Path("/current")),
                patch("builtins.open", unittest.mock.mock_open()),
                patch.object(guard.fcntl, "flock"),
                patch.object(Path, "resolve", return_value=Path("/candidate")),
                patch.object(
                    guard,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, "active"),
                ),
                patch("builtins.print"),
                self.assertRaisesRegex(AssertionError, "timer is still active"),
            ):
                guard.main("disarm", "/candidate")
            self.assertTrue(state.exists())
            self.assertTrue(root.is_symlink())

    def test_rollback_restores_access_before_activating_previous_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            state = base / "state"
            state.mkdir()
            previous = base / "previous"
            (previous / "etcFiles").mkdir(parents=True)
            root = base / "gcroot"
            root.symlink_to(previous)
            etc = base / "etc"
            files = {}
            for name in [
                "ssh/sshd_config.d/10-homelab.conf",
                "nftables.conf",
                "systemd/system",
            ]:
                path = base / "sources" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if name == "systemd/system":
                    path.mkdir()
                    (path / "homelab-firewall.service").write_text(
                        "ExecStart=/nix/store/old-nft/bin/nft -f /etc/nftables.conf\n"
                    )
                else:
                    path.write_text("previous configuration")
                    target = etc / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("candidate configuration")
                files[name] = {
                    "enable": True,
                    "source": str(base / "sources"),
                    "target": name,
                }
            (previous / "etcFiles/etcFiles.json").write_text(
                json.dumps({"entries": files})
            )
            with (
                patch.object(guard, "STATE", state),
                patch.object(guard, "ROOT", root),
                patch.object(guard, "ETC", etc),
                patch("builtins.open", unittest.mock.mock_open()),
                patch.object(guard.fcntl, "flock"),
                patch.object(guard, "run") as run,
            ):
                guard.main("rollback")
                self.assertEqual(
                    (etc / "nftables.conf").read_text(), "previous configuration"
                )
                self.assertEqual(
                    run.call_args_list[0].args[0], "/nix/store/old-nft/bin/nft"
                )
                self.assertEqual(
                    run.call_args_list[-1].args, (str(previous / "bin/activate"),)
                )
                self.assertTrue(root.exists())
                with self.assertRaisesRegex(RuntimeError, "Rollback has started"):
                    guard.main("disarm", "/candidate")

    def test_disarm_failure_keeps_recovery_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / "candidate").write_text("/candidate")
            with (
                patch.object(guard, "STATE", state),
                patch("builtins.open", unittest.mock.mock_open()),
                patch.object(guard.fcntl, "flock"),
                patch.object(Path, "resolve", return_value=Path("/old")),
                patch.object(guard, "run") as run,
                self.assertRaisesRegex(RuntimeError, "no longer active"),
            ):
                guard.main("disarm", "/candidate")
            run.assert_not_called()
            self.assertTrue((state / "candidate").exists())

    def test_failed_guard_verification_does_not_activate(self):
        with (
            patch("sys.argv", ["deploy.py", "deploy"]),
            patch.object(deploy, "snapshot", return_value=Path("/source")),
            patch.object(deploy, "build", return_value="/candidate"),
            patch.object(deploy, "check_access", return_value="machine"),
            patch.object(deploy, "check_storage"),
            patch.object(deploy.subprocess, "run"),
            patch.object(
                deploy,
                "deployment_guard",
                side_effect=RuntimeError("timer is not waiting"),
            ),
            patch.object(deploy, "ssh") as activate,
            patch.object(deploy, "check_health") as health,
            patch.object(deploy, "check_stability") as stability,
        ):
            self.assertEqual(deploy.main(), 1)
        activate.assert_not_called()
        health.assert_not_called()
        stability.assert_not_called()

    def test_failed_activation_or_health_does_not_disarm(self):
        for failure in ("activate", "health", "stability", None):
            with (
                self.subTest(failure=failure),
                patch("sys.argv", ["deploy.py", "deploy"]),
                patch.object(deploy, "snapshot", return_value=Path("/source")),
                patch.object(deploy, "build", return_value="/candidate"),
                patch.object(deploy, "check_access", return_value="machine"),
                patch.object(deploy.subprocess, "run"),
                patch.object(deploy, "deployment_guard", return_value="") as gate,
                patch.object(deploy, "ssh", return_value="") as ssh,
                patch.object(deploy, "check_health") as health,
                patch.object(deploy, "check_storage"),
                patch.object(deploy, "check_stability") as stability,
            ):
                if failure == "activate":
                    ssh.side_effect = deploy.subprocess.CalledProcessError(
                        1, "activate"
                    )
                if failure == "health":
                    health.side_effect = RuntimeError("unhealthy")
                if failure == "stability":
                    stability.side_effect = RuntimeError("service restarted")
                self.assertEqual(deploy.main(), int(failure is not None))
                health.assert_called_once()
                if failure in ("activate", "health"):
                    stability.assert_not_called()
                else:
                    stability.assert_called_once()
                self.assertEqual(
                    [call.args[2] for call in gate.call_args_list],
                    ["arm"] if failure else ["arm", "disarm"],
                )


if __name__ == "__main__":
    unittest.main()
