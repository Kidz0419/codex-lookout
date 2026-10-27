import contextlib
import importlib.util
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "native" / "monitor.py"
SPEC = importlib.util.spec_from_file_location("native_monitor", SCRIPT)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, "CODEX_HOME": str(self.home)}

    def run_once(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPT), "--once", *args], cwd=str(self.home), env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(len(result.stdout.splitlines()), 1)
        return json.loads(result.stdout)

    def test_once_honors_codex_home_and_reports_missing_sources(self):
        snapshot = self.run_once()
        self.assertEqual(snapshot["tasks"], [])
        self.assertEqual(snapshot["taskLimit"], 200)
        self.assertFalse(next(s for s in snapshot["sources"] if s["name"] == "state_5.sqlite")["available"])
        self.assertIn("generatedAt", snapshot)

    def test_process_preserves_parent_and_agent_metadata(self):
        rollout = self.home / "rollout.jsonl"
        rollout.write_text("")
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as conn:
            conn.executescript("""
                CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, name TEXT,
                    cwd TEXT, source TEXT, model TEXT, updated_at INTEGER, archived INTEGER,
                    agent_nickname TEXT, agent_path TEXT, agent_role TEXT);
                CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT);
            """)
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("child-id", str(rollout), "", None, "/fixture", "vscode", "test-model", 1800000000, 0, "Helmholtz", "/root/collector", "reviewer"))
            conn.execute("INSERT INTO thread_spawn_edges VALUES (?,?)", ("parent-id", "child-id"))
        first = self.run_once("--limit", "1")["tasks"][0]
        second = self.run_once("--limit", "1")["tasks"][0]
        for key in ("id", "parentId", "title", "agentPath", "agentRole"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["parentId"], "parent-id")
        self.assertEqual(first["title"], "子任务 · Helmholtz")
        self.assertEqual(first["agentPath"], "/root/collector")

    def test_bundled_helper_imports_adjacent_collector(self):
        backend = self.home / "Resources" / "backend"
        backend.mkdir(parents=True)
        shutil.copyfile(SCRIPT, backend / "monitor.py")
        shutil.copyfile(ROOT / "collector.py", backend / "collector.py")
        result = subprocess.run([sys.executable, str(backend / "monitor.py"), "--once"], cwd=str(self.home), env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("sources", json.loads(result.stdout))

    def test_exception_is_safe_error_record_and_not_empty_snapshot(self):
        class BrokenCollector:
            def __init__(self, home, limit):
                pass

            def snapshot(self):
                raise RuntimeError("PRIVATE CONTENT /secret/path")

        output = io.StringIO()
        with patch.object(monitor, "_load_collector", return_value=BrokenCollector), contextlib.redirect_stdout(output):
            self.assertEqual(monitor.main(["--once"]), 0)
        error = json.loads(output.getvalue())
        self.assertEqual(error["type"], "collectorError")
        self.assertEqual(error["errorType"], "RuntimeError")
        self.assertTrue(error["generatedAt"].endswith("Z"))
        self.assertNotIn("tasks", error)
        self.assertNotIn("PRIVATE CONTENT", output.getvalue())
        self.assertNotIn("/secret/path", output.getvalue())

    def test_persistent_loop_recovers_after_sample_exception(self):
        class RecoveringCollector:
            calls = 0

            def __init__(self, home, limit):
                pass

            def snapshot(self):
                self.calls += 1
                if self.calls == 1:
                    raise OSError("private failure")
                return {"tasks": [], "generatedAt": "recovered", "sources": []}

        output = io.StringIO()
        with patch.object(monitor, "_load_collector", return_value=RecoveringCollector), patch.object(monitor.time, "sleep", side_effect=[None, KeyboardInterrupt]), contextlib.redirect_stdout(output):
            self.assertEqual(monitor.main(["--interval", "0.01"]), 0)
        lines = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(lines[0]["type"], "collectorError")
        self.assertEqual(lines[1]["generatedAt"], "recovered")

    def test_broken_pipe_exits_quietly(self):
        process = subprocess.Popen([sys.executable, str(SCRIPT), "--interval", "0.01"], cwd=str(self.home), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        process.stdout.close()
        self.assertEqual(process.wait(timeout=5), 0)
        self.assertEqual(process.stderr.read(), b"")
        process.stderr.close()

    def test_invalid_interval_rejected(self):
        for value in ("0", "-2", "nan", "inf"):
            with self.subTest(value=value):
                result = subprocess.run([sys.executable, str(SCRIPT), "--once", "--interval", value], env=self.env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
