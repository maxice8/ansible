import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import helpers

ROOT = Path(__file__).resolve().parent.parent


class SimplificationChecks(unittest.TestCase):
    def test_interface_validation(self):
        with patch.object(helpers, "host") as host:
            host.get_fact.return_value = "enp0s6"
            self.assertEqual(helpers.get_public_interface(), "enp0s6")
            for value in (None, "", "eth0; reboot", "eth0\neth1"):
                host.get_fact.return_value = value
                with self.assertRaisesRegex(RuntimeError, "public network interface"):
                    helpers.get_public_interface()

    def test_manifest_reconciliation(self):
        with (
            patch.object(helpers, "host") as host,
            patch.object(helpers.files, "put") as put,
            patch.object(helpers.server, "shell") as shell,
        ):
            for changed, state in (
                (False, "current"),
                (True, "current"),
                (False, "drifted"),
            ):
                put.return_value.changed = changed
                host.get_fact.return_value = state
                shell.reset_mock()
                helpers.apply_manifest(
                    "test", "test", "kind: ConfigMap\n", after=("restart",)
                )
                self.assertEqual(shell.called, changed or state != "current")
                if shell.called:
                    self.assertEqual(
                        shell.call_args.kwargs["commands"],
                        ["k3s kubectl apply -f /usr/local/src/test.yaml", "restart"],
                    )

    def test_make_update_errors_and_alias(self):
        for args, expected in (
            ([], "missing service. Use: make update"),
            (
                ["service=pomerum", "version=1.2.3"],
                "unknown service 'pomerum'. Available services:",
            ),
            (
                ["service=pomerium"],
                "missing version. Use: make update service=pomerium",
            ),
            (["service=pomerium", "version=invalid"], "invalid version: 'invalid'"),
        ):
            result = subprocess.run(
                ["make", "--no-print-directory", "update", *args],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
        result = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "update",
                "service=archisteamfarm",
                "version=0.0.0",
                "dry_run=1",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Would update", result.stdout)


if __name__ == "__main__":
    unittest.main()
