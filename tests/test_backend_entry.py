"""Tests for the exact command dispatcher used by frozen release builds."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENTRY = Path(__file__).resolve().parents[1] / "native" / "backend_entry.py"


class BackendEntryTests(unittest.TestCase):
    def test_monitor_dispatch_works_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, str(ENTRY), "monitor", "--once", "--limit", "1"],
                                    env={**os.environ, "CODEX_HOME": directory}, cwd=directory,
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["taskLimit"], 1)
        self.assertEqual(snapshot["tasks"], [])
        self.assertEqual(result.stderr, "")

    def test_server_dispatch_forwards_its_arguments(self):
        result = subprocess.run([sys.executable, str(ENTRY), "server", "--help"],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--port", result.stdout)
        self.assertIn("--codex-home", result.stdout)

    def test_unknown_command_fails_instead_of_starting_a_service(self):
        result = subprocess.run([sys.executable, str(ENTRY), "invalid-command"],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
