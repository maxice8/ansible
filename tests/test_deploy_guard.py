"""Check deployment access gates and rollback cancellation."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import deploy
from scripts import deploy_guard as guard


class GuardTests(unittest.TestCase):
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
                guard.main("arm", "/candidate")
                preflight.assert_called_once_with("/candidate")
                self.assertEqual(root.resolve(), previous)
                self.assertIn("--on-active=30m", run.call_args.args)
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
                run.assert_called_with("systemctl", "stop", guard.UNIT + ".timer")

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

    def test_failed_activation_or_health_does_not_disarm(self):
        for failure in ("activate", "health", None):
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
            ):
                if failure == "activate":
                    ssh.side_effect = deploy.subprocess.CalledProcessError(
                        1, "activate"
                    )
                if failure == "health":
                    health.side_effect = RuntimeError("unhealthy")
                self.assertEqual(deploy.main(), int(failure is not None))
                self.assertEqual(
                    [call.args[2] for call in gate.call_args_list],
                    ["arm"] if failure else ["arm", "disarm"],
                )


if __name__ == "__main__":
    unittest.main()
