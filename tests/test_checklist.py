"""Check terminal rendering and remote progress without deploying."""

import io
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.checklist import Checklist
from tests.test_vps import ssh


class ChecklistTests(unittest.TestCase):
    def test_plain_output_has_nested_checks_and_no_escape_codes(self):
        stream = io.StringIO()
        report = Checklist(stream)
        report.title("Deploy · Mashu")
        for line in ("GROUP\tDNS", "CHECK\tUnbound UDP", "PASS\tUnbound UDP"):
            report.feed(line)
        report.feed("Evaluating pre-activation assertion...")
        with self.assertRaises(RuntimeError), report.step("Activate services"):
            raise RuntimeError("failed")
        output = stream.getvalue()
        self.assertIn("\n  DNS\n    ✓ Unbound UDP\n", output)
        self.assertIn("\n  ✗ Activate services", output)
        self.assertNotIn("\033", output)
        self.assertNotIn("Evaluating", output)

    def test_terminal_replaces_active_line_and_uses_semantic_colours(self):
        stream = io.StringIO()
        stream.isatty = lambda: True
        with patch.dict(os.environ, {"TERM": "xterm"}):
            with patch.dict(os.environ):
                os.environ.pop("NO_COLOR", None)
                report = Checklist(stream)
                with report.step("Rollback armed · 30 minutes"):
                    self.assertIn("\033[36m◌", stream.getvalue())
                self.assertIn("\r\033[2K", stream.getvalue())
                self.assertIn("\033[32m✓", stream.getvalue())
                self.assertIn("\033[33mRollback armed", stream.getvalue())
                report.feed("GROUP\tRollback")
                report.feed("CHECK\tTimer armed · 30 minutes")
                report.feed("PASS\tTimer armed · 30 minutes")
                self.assertIn("\033[33mTimer armed · 30 minutes", stream.getvalue())
            with patch.dict(os.environ, {"NO_COLOR": "1"}):
                self.assertEqual(Checklist(stream).style("text", "32"), "text")
            with patch.dict(os.environ, {"TERM": "dumb"}):
                self.assertFalse(Checklist(stream).terminal)

    def test_remote_failure_marks_the_active_check(self):
        stream = io.StringIO()
        report = Checklist(stream)
        report.feed("GROUP\tApplications")
        report.feed("CHECK\tForgejo")
        report.fail_active()
        self.assertIn("    ✗ Forgejo", stream.getvalue())
        self.assertNotIn("✓ Forgejo", stream.getvalue())


class StreamingTests(unittest.TestCase):
    def run_remote(self, script, callback, timeout=5):
        popen = subprocess.Popen

        def local_python(command, **kwargs):
            return popen([sys.executable, "-"], **kwargs)

        with patch("tests.test_vps.subprocess.Popen", side_effect=local_python):
            return ssh("unused", [], script, on_line=callback, timeout=timeout)

    def test_streams_before_exit_and_keeps_stderr_on_failure(self):
        lines = []
        script = """import sys
print('GROUP\\tDNS',flush=True)
print('CHECK\\tUnbound TCP',flush=True)
print('resolution failed',file=sys.stderr)
sys.exit(7)
"""
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            self.run_remote(script, lines.append)
        self.assertEqual(lines, ["GROUP\tDNS", "CHECK\tUnbound TCP"])
        self.assertEqual(caught.exception.returncode, 7)
        self.assertIn("resolution failed", caught.exception.stderr)
        self.assertIn("CHECK\tUnbound TCP", caught.exception.stdout)

    def test_partial_lines_and_large_output_do_not_block(self):
        lines = []
        output = self.run_remote(
            "import sys; print('x'*100000); sys.stdout.write('tail')", lines.append
        )
        self.assertEqual(lines, ["x" * 100000, "tail"])
        self.assertEqual(output, "x" * 100000 + "\ntail")

    def test_timeout_keeps_progress_and_diagnostics(self):
        lines = []
        script = """import sys,time
print('CHECK\\tForgejo',flush=True)
print('still waiting',file=sys.stderr,flush=True)
time.sleep(10)
"""
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            self.run_remote(script, lines.append, timeout=0.5)
        self.assertEqual(lines, ["CHECK\tForgejo"])
        self.assertIn("still waiting", caught.exception.stderr)
        self.assertIn("CHECK\tForgejo", caught.exception.stdout)


if __name__ == "__main__":
    unittest.main()
