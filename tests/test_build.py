"""Check build output handling."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import deploy


class BuildTests(unittest.TestCase):
    def test_build_keeps_progress_visible_and_returns_profile(self):
        with (
            patch.object(deploy.shutil, "which", return_value="/bin/nom"),
            patch.object(
                deploy.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 0, stdout="/nix/store/profile\n"
                ),
            ) as run,
        ):
            self.assertEqual(
                deploy.build(Path("/source"), "systemConfigs.mashu", "none"),
                "/nix/store/profile",
            )

        self.assertEqual(
            run.call_args.kwargs,
            {
                "text": True,
                "stdout": subprocess.PIPE,
                "check": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
