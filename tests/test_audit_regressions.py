"""Independent regressions derived from observed Codex persistence behavior."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import Collector


class AuditRegressions(unittest.TestCase):
    NOW = 1_793_101_400

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.rollout = self.home / "turn.jsonl"
        self.start = self.NOW - 60
        self.records = []
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("CREATE TABLE threads (id TEXT, title TEXT, cwd TEXT, model TEXT, source TEXT, archived INTEGER, updated_at INTEGER, rollout_path TEXT)")
            db.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?)", ("thread-1", "Audit fixture", "/fixture", "test", "cli", 0, self.NOW, str(self.rollout)))
            db.execute("CREATE TABLE thread_spawn_edges (child_thread_id TEXT, parent_thread_id TEXT)")
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER, status TEXT, started_at INTEGER, completed_at INTEGER, rollout_byte_offset INTEGER)")
            db.execute("INSERT INTO thread_turns VALUES (?, ?, ?, ?, ?, ?, ?)", ("thread-1", "turn-current", 100, "inProgress", self.start, None, 0))
            db.execute("CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER, created_at_ms INTEGER, started_at_ms INTEGER, completed_at_ms INTEGER, item_type TEXT, item_json TEXT)")
        with sqlite3.connect(self.home / "logs_2.sqlite") as db:
            db.execute("CREATE TABLE logs (thread_id TEXT, ts INTEGER, ts_nanos INTEGER, level TEXT, target TEXT, feedback_log_body TEXT)")
        self.record(self.start, "event_msg", {"type": "task_started", "turn_id": "turn-current"})

    def tearDown(self):
        self.temp.cleanup()

    def record(self, at, outer, payload):
        self.records.append({"timestamp": at, "type": outer, "payload": payload})
        self.rollout.write_text("".join(json.dumps(r) + "\n" for r in self.records))

    def log(self, at, body, target="codex_core::responses_retry"):
        with sqlite3.connect(self.home / "logs_2.sqlite") as db:
            db.execute("INSERT INTO logs VALUES (?, ?, ?, ?, ?, ?)", ("thread-1", at, 0, "WARN", target, body))

    def task(self):
        return Collector(self.home).snapshot(now=self.NOW)["tasks"][0]

    def test_late_error_from_previous_turn_does_not_implicate_current_turn(self):
        self.log(self.NOW - 5, 'turn{thread.id=thread-1 turn.id=turn-old}: stream disconnected - retrying sampling request turn_id=turn-old retries=1 max_retries=5')
        task = self.task()
        self.assertEqual(task["networkErrors"], [])
        self.assertNotEqual(task["diagnosis"]["code"], "connection_retry")

    def test_fresh_correlated_retry_counts_as_visible_activity(self):
        self.start = self.NOW - 1800
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("UPDATE thread_turns SET started_at=?", (self.start,))
        self.records = []
        self.record(self.start, "event_msg", {"type": "task_started", "turn_id": "turn-current"})
        self.log(self.NOW - 3, 'turn{thread.id=thread-1 turn.id=turn-current}: stream disconnected - retrying sampling request turn_id=turn-current retries=2 max_retries=5')
        task = self.task()
        self.assertTrue(task["networkErrors"])
        self.assertLessEqual(task["silenceSeconds"], 5, "A fresh observed retry must not be described as 30 minutes of no events")

    def test_completed_tool_with_missing_completion_timestamp_is_not_running(self):
        item = {"type": "mcpToolCall", "id": "tool-item", "tool": "safe_tool", "status": "completed", "arguments": {"text": "PRIVATE_ARGUMENT"}, "result": {"text": "PRIVATE_RESULT"}}
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("thread-1", "turn-current", "tool-item", 102, (self.NOW - 20) * 1000, (self.NOW - 20) * 1000, None, "mcpToolCall", json.dumps(item)))
        task = self.task()
        self.assertIsNone(task["currentTool"])
        self.assertNotEqual(task["phase"], "tool")
        self.assertNotIn("PRIVATE_ARGUMENT", json.dumps(task))
        self.assertNotIn("PRIVATE_RESULT", json.dumps(task))

    def test_explicit_history_completion_resolves_unmatched_rollout_start(self):
        self.record(self.NOW - 20, "response_item", {"type": "function_call", "name": "exec_command", "call_id": "finished-call", "arguments": "{}"})
        item = {"type": "commandExecution", "id": "finished-call", "status": "completed"}
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("INSERT INTO thread_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", ("thread-1", "turn-current", "finished-call", 103, (self.NOW - 20) * 1000, (self.NOW - 20) * 1000, (self.NOW - 10) * 1000, "commandExecution", json.dumps(item)))
        task = self.task()
        self.assertIsNone(task["currentTool"], "An explicit completed status must take precedence over a missing return event")
        self.assertNotEqual(task["phase"], "tool")

    def test_sparse_usage_and_message_content_never_become_rate_or_payload(self):
        self.record(self.NOW - 45, "response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "PRIVATE_MODEL_TEXT"}]})
        self.record(self.NOW - 40, "token_usage_record", {"turn_id": "turn-current", "turn_token_usage": {"output_tokens": 100, "reasoning_output_tokens": 40, "total_tokens": 1000}})
        self.record(self.NOW - 10, "token_usage_record", {"turn_id": "turn-current", "turn_token_usage": {"output_tokens": 200, "reasoning_output_tokens": 50, "total_tokens": 1300}})
        task = self.task()
        self.assertEqual(task["tokens"]["output"], 200)
        self.assertIsNone(task["tokens"]["rate"])
        self.assertNotIn("PRIVATE_MODEL_TEXT", json.dumps(task))

    def test_network_words_in_tool_arguments_do_not_create_incident(self):
        self.record(self.NOW - 20, "response_item", {"type": "function_call", "name": "exec_command", "call_id": "c1", "arguments": '{"cmd":"echo network timeout broken pipe retry"}'})
        self.record(self.NOW - 15, "response_item", {"type": "function_call_output", "call_id": "c1", "output": "network timeout broken pipe retry"})
        self.log(self.NOW - 10, "ToolCall arguments network timeout broken pipe retry", target="codex_core::tools::parallel")
        self.assertEqual(self.task()["networkErrors"], [])

    def test_old_inprogress_without_new_evidence_becomes_unknown(self):
        with sqlite3.connect(self.home / "thread_history_1.sqlite") as db:
            db.execute("UPDATE thread_turns SET started_at=?", (self.NOW - 30 * 86400,))
        self.records = []
        self.record(self.NOW - 30 * 86400, "event_msg", {"type": "task_started", "turn_id": "turn-current"})
        task = self.task()
        self.assertEqual(task["status"], "unknown")
        self.assertIsNone(task["currentTool"])


if __name__ == "__main__":
    unittest.main()
