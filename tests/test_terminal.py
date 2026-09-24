"""Actual Linux terminal startup and keyboard exit, separate from headless UI tests."""

import fcntl
import importlib.util
import os
from pathlib import Path
import pty
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest

from foundry.workflow import Workflow
from tests.fixtures import source
from tests.workflow_fixtures import populated


@unittest.skipUnless(importlib.util.find_spec("textual"), "requires pinned Textual dependencies")
class TerminalTests(unittest.TestCase):
    def test_actual_native_terminal_starts_and_ctrl_q_exits(self):
        with tempfile.TemporaryDirectory() as root:
            flow = Workflow(Path(root) / "workflow", "synthetic")
            flow.initialize()
            populated(flow, root)
            # Enough varied source text to exercise completion after the UI has
            # begun awaiting a worker, rather than an already-completed future.
            def more_material(state):
                state["core"]["sources"].extend(
                    source(f"extra-{n}", f"Fictional source {n}. " + "selected synthetic text " * 600)
                    for n in range(24))
            flow.update(more_material, "synthetic terminal test load")
            pid, master = pty.fork()
            if pid == 0:
                os.execv(sys.executable, [sys.executable, "-B", "-m", "foundry", "ui", "--dataset", "synthetic",
                                         "--workspace", str(flow.path)])
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 110, 0, 0))
            output, done = b"", 0
            try:
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline and b"More" not in output:
                    if select.select([master], [], [], 0.1)[0]:
                        chunk = os.read(master, 65536)
                        output += chunk
                        for mode in (b"2026", b"2048"):
                            if b"\x1b[?" + mode + b"$p" in chunk:
                                os.write(master, b"\x1b[?" + mode + b";2$y")
                self.assertIn(b"More", output, "the actual terminal must paint its navigation")
                os.write(master, b"\x11")
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    done, status = os.waitpid(pid, os.WNOHANG)
                    if done:
                        break
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            os.read(master, 65536)
                        except OSError:
                            pass
                self.assertTrue(done, "Ctrl+Q must exit without hanging")
                self.assertEqual(os.waitstatus_to_exitcode(status), 0)
            finally:
                if not done:
                    os.kill(pid, signal.SIGTERM)
                    os.kill(pid, signal.SIGCONT)
                    os.waitpid(pid, 0)
                os.close(master)
