"""Show deployment stages and checks in a terminal or plain log."""

import os
import sys
import time
from contextlib import contextmanager


class Checklist:
    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout
        self.terminal = self.stream.isatty() and os.environ.get("TERM") != "dumb"
        self.colour = self.terminal and "NO_COLOR" not in os.environ
        self.active = None
        self.separate_stage = False

    def style(self, text, code):
        return f"\033[{code}m{text}\033[0m" if self.colour else text

    def line(self, text):
        print(text, file=self.stream, flush=True)

    def title(self, text):
        self.line(self.style(text, "1"))
        self.separate_stage = True

    def group(self, text):
        self.line("\n  " + self.style(text, "1"))
        self.separate_stage = True

    def start(self, text, *, child=False):
        if not child and self.separate_stage:
            self.line("")
            self.separate_stage = False
        self.active = (text, child, time.monotonic())
        if self.terminal:
            indent = "    " if child else "  "
            print(
                indent + self.style("◌", "36") + " " + text + "…",
                end="",
                file=self.stream,
                flush=True,
            )

    def finish(self, success=True):
        text, child, started = self.active
        self.active = None
        if self.terminal:
            print("\r\033[2K", end="", file=self.stream)
        indent = "    " if child else "  "
        symbol = self.style("✓" if success else "✗", "32" if success else "31")
        duration = (
            "" if child else self.style(f"  {time.monotonic() - started:.0f}s", "2")
        )
        code = "33" if "Rollback armed" in text else "1"
        label = text if child else self.style(text, code)
        if text == "Timer armed · 30 minutes":
            label = self.style(text, "33")
        self.line(f"{indent}{symbol} {label}{duration}")

    @contextmanager
    def step(self, text, *, child=False):
        self.start(text, child=child)
        try:
            yield
        except BaseException:
            self.finish(False)
            raise
        else:
            self.finish()

    def feed(self, line):
        """Read check events from a remote script. Keep other output for errors."""
        event, separator, text = line.rstrip("\n").partition("\t")
        if not separator:
            return
        if event == "GROUP":
            self.group(text)
        elif event == "CHECK":
            self.start(text, child=True)
        elif event == "PASS":
            self.finish()
        elif event == "DONE":
            self.start(text)
            self.finish()

    def fail_active(self):
        if self.active is not None:
            self.finish(False)
