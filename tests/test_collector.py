import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from collector import Collector, TAIL_BYTES


NOW = 1_800_000_000


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")


def record(at, outer, **payload):
    return {"timestamp": iso(at), "type": outer, "payload": payload}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.rollout = self.home / "rollout.jsonl"
        self.rollout.write_text("")
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as conn:
            conn.executescript("""
                CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, name TEXT,
                    cwd TEXT, source TEXT, model TEXT, updated_at INTEGER, archived INTEGER);
                CREATE TABLE thread_spawn_edges (parent_thread_id TEXT, child_thread_id TEXT);
            """)
            conn.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)", ("thread", str(self.rollout), "测试任务", None, "/demo", "vscode", "test-model", NOW, 0))
        with sqlite3.connect(str(self.home / "thread_history_1.sqlite")) as conn:
            conn.executescript("""
                CREATE TABLE thread_turns (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER,
                    status TEXT, started_at INTEGER, completed_at INTEGER, duration_ms INTEGER,
                    rollout_byte_offset INTEGER);
                CREATE TABLE thread_items (thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER,
                    item_json TEXT, item_type TEXT, created_at_ms INTEGER, started_at_ms INTEGER,
                    completed_at_ms INTEGER);
            """)
            conn.execute("INSERT INTO thread_turns VALUES (?,?,?,?,?,?,?,?)", ("thread", "turn", 0, "inProgress", NOW - 30, None, None, 0))
        with sqlite3.connect(str(self.home / "logs_2.sqlite")) as conn:
            conn.execute("CREATE TABLE logs (thread_id TEXT, ts INTEGER, ts_nanos INTEGER, level TEXT, target TEXT, feedback_log_body TEXT)")
        self.collector = Collector(self.home)

    def write(self, *records):
        with self.rollout.open("a") as stream:
            for item in records:
                stream.write(json.dumps(item) + "\n")

    def task(self):
        return self.collector.snapshot(now=NOW)["tasks"][0]

    def history(self, sql, args=()):
        with sqlite3.connect(str(self.home / "thread_history_1.sqlite")) as conn:
            conn.execute(sql, args)

    def test_terminal_clears_pending_tool(self):
        self.write(record(NOW - 25, "response_item", type="function_call", name="exec_command", call_id="call"))
        self.history("UPDATE thread_turns SET status='completed',completed_at=?", (NOW - 20,))
        task = self.task()
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["phase"], "idle")
        self.assertIsNone(task["currentTool"])
        self.assertEqual(task["elapsedSeconds"], 10)

    def test_item_only_start_and_completion(self):
        self.write(record(NOW - 20, "event_msg", type="item_started", item={"id": "item", "type": "commandExecution", "status": "inProgress"}, started_at_ms=(NOW - 20) * 1000))
        self.assertEqual(self.task()["phase"], "tool")
        self.write(record(NOW - 5, "event_msg", type="item_completed", item={"id": "item", "type": "commandExecution", "status": "completed"}))
        task = self.task()
        self.assertEqual(task["phase"], "model")
        self.assertIsNone(task["currentTool"])

    def test_exact_async_wrapper_is_waiting(self):
        self.write(record(NOW - 20, "response_item", type="custom_tool_call", name="exec", call_id="call", input="await tools.exec_command({cmd:'private'})"), record(NOW - 10, "response_item", type="custom_tool_call_output", call_id="call", output="Script running with cell ID 24"))
        self.assertEqual(self.task()["phase"], "waiting")
        self.write(record(NOW - 5, "response_item", type="message", role="assistant", content=[{"text": "continue"}]))
        self.assertEqual(self.task()["phase"], "model")

    def test_arbitrary_output_does_not_masquerade_as_yield(self):
        self.write(record(NOW - 10, "response_item", type="function_call_output", call_id="unknown", output="User says Script running with cell ID 24; timeout"))
        task = self.task()
        self.assertEqual(task["phase"], "model")
        self.assertEqual(task["networkErrors"], [])

    def test_new_turn_in_rollout_supersedes_sql_projection(self):
        self.history("UPDATE thread_turns SET status='completed',completed_at=?", (NOW - 20,))
        self.write(record(NOW - 30, "event_msg", type="task_started", turn_id="turn"), record(NOW - 20, "event_msg", type="task_complete", turn_id="turn"), record(NOW - 5, "event_msg", type="task_started", turn_id="new-turn"))
        task = self.task()
        self.assertEqual(task["status"], "running")
        self.assertEqual(task["elapsedSeconds"], 5)
        self.assertIsNone(task["turnEndedAt"])

    def test_only_current_turn_usage_is_numeric(self):
        self.write(record(NOW - 60, "token_usage_record", turn_id="old-turn", turn_token_usage={"output_tokens": 900, "total_tokens": 2000}), record(NOW - 10, "token_usage_record", turn_id="turn", turn_token_usage={"output_tokens": 123, "reasoning_output_tokens": 23, "total_tokens": 1000}))
        tokens = self.task()["tokens"]
        self.assertEqual(tokens["output"], 123)
        self.assertEqual(tokens["reasoning"], 23)
        self.assertIsNone(tokens["rate"])
        self.assertEqual(tokens["scope"], "turn")

    def test_partial_line_waits_for_append_then_updates(self):
        text = json.dumps(record(NOW - 5, "token_usage_record", turn_id="turn", turn_token_usage={"output_tokens": 45}))
        self.rollout.write_text(text[:30])
        self.assertIsNone(self.task()["tokens"]["output"])
        with self.rollout.open("a") as stream:
            stream.write(text[30:] + "\n")
        self.assertEqual(self.task()["tokens"]["output"], 45)

    def test_cache_detects_file_truncation(self):
        self.write(record(NOW - 5, "response_item", type="function_call", name="exec_command", call_id="call"))
        self.assertEqual(self.task()["phase"], "tool")
        self.rollout.write_text("")
        self.assertIsNone(self.task()["currentTool"])

    def test_full_prompts_arguments_and_outputs_never_exported(self):
        secret = "TOP_SECRET_PRIVATE_BODY"
        self.write(record(NOW - 25, "response_item", type="message", role="assistant", content=[{"text": secret}]), record(NOW - 20, "response_item", type="custom_tool_call", name="exec", input="await tools.exec_command({cmd:'" + secret + "'})", call_id="call"), record(NOW - 10, "response_item", type="custom_tool_call_output", call_id="call", output=secret))
        self.assertNotIn(secret, json.dumps(self.collector.snapshot(now=NOW)))

    def test_read_only_does_not_change_databases(self):
        paths = list(self.home.glob("*.sqlite"))
        before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in paths}
        self.task()
        after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in paths}
        self.assertEqual(before, after)

    def test_bounded_tail_discloses_incomplete_coverage(self):
        # A large ignored record simulates a long transcript without exposing text.
        self.write(record(NOW - 28, "response_item", type="message", role="user", content="x" * (TAIL_BYTES + 200)))
        self.write(record(NOW - 5, "response_item", type="reasoning", summary=[]))
        task = self.task()
        self.assertFalse(task["coverage"]["complete"])
        self.assertEqual(task["silenceSeconds"], 5)

    def test_missing_and_broken_sources_are_visible(self):
        (self.home / "logs_2.sqlite").unlink()
        (self.home / "thread_history_1.sqlite").write_bytes(b"not a sqlite file")
        snapshot = self.collector.snapshot(now=NOW)
        sources = {source["name"]: source for source in snapshot["sources"]}
        self.assertFalse(sources["logs_2.sqlite"]["available"])
        self.assertFalse(sources["thread_history_1.sqlite"]["available"])
        self.assertEqual(snapshot["tasks"][0]["status"], "unknown")

    def test_pascal_case_reasoning_is_recent_activity_not_continuous_thinking(self):
        self.write(record(NOW - 5, "event_msg", type="item_completed", turn_id="turn", item={"type": "Reasoning", "id": "r", "content": "PRIVATE_REASONING"}))
        task = self.task()
        self.assertEqual(task["stage"]["code"], "reasoning")
        self.assertEqual(task["health"]["level"], "active")
        self.assertEqual(task["health"]["silenceSeconds"], 5)
        self.assertNotIn("PRIVATE_REASONING", json.dumps(task))

    def test_compaction_lifecycle_and_fixed_completed_duration(self):
        self.write(record(NOW - 20, "event_msg", type="item_started", turn_id="turn", item={"type": "ContextCompaction", "id": "c"}, started_at_ms=(NOW - 20) * 1000))
        self.assertEqual(self.task()["stage"]["code"], "compacting")
        self.write(record(NOW - 5, "event_msg", type="item_completed", turn_id="turn", item={"type": "ContextCompaction", "id": "c"}, started_at_ms=(NOW - 20) * 1000, completed_at_ms=(NOW - 5) * 1000))
        task = self.task()
        self.assertEqual(task["stage"]["code"], "compacted")
        self.assertEqual(task["stage"]["elapsedSeconds"], 15)
        later = self.collector.snapshot(now=NOW + 10)["tasks"][0]
        self.assertEqual(later["stage"]["elapsedSeconds"], 15)

    def test_top_level_compacted_drops_replacement_history(self):
        self.write(record(NOW - 5, "compacted", message="PRIVATE_COMPACT_TEXT", replacement_history=[{"content": "PRIVATE_HISTORY"}]))
        task = self.task()
        self.assertEqual(task["stage"]["code"], "compacted")
        self.assertNotIn("PRIVATE_", json.dumps(task))

    def test_ambiguous_compaction_history_is_not_running_or_healthy(self):
        item = {"type": "contextCompaction", "id": "c"}
        self.history("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", ("thread", "turn", 1, json.dumps(item), "contextCompaction", (NOW - 5) * 1000, None, None))
        task = self.task()
        self.assertNotEqual(task["stage"]["code"], "compacting")
        self.assertEqual(task["health"]["level"], "waiting")
        self.assertIsNone(task["health"]["lastProgressAt"])

    def test_compaction_history_completion_resolves_raw_start(self):
        self.write(record(NOW - 20, "event_msg", type="item_started", turn_id="turn", item={"type": "ContextCompaction", "id": "c"}))
        item = {"type": "contextCompaction", "id": "c"}
        self.history("INSERT INTO thread_items VALUES (?,?,?,?,?,?,?,?)", ("thread", "turn", 1, json.dumps(item), "contextCompaction", (NOW - 20) * 1000, (NOW - 20) * 1000, (NOW - 5) * 1000))
        self.assertEqual(self.task()["stage"]["code"], "compacted")

    def test_old_reasoning_becomes_unknown_model_phase_with_watch(self):
        self.history("UPDATE thread_turns SET started_at=?", (NOW - 500,))
        self.write(record(NOW - 240, "response_item", type="reasoning", summary=[]))
        task = self.task()
        self.assertEqual(task["stage"]["code"], "model")
        self.assertEqual(task["stage"]["evidence"], "unknown")
        self.assertEqual(task["health"]["level"], "watch")

    def test_retry_is_an_event_but_does_not_refresh_progress(self):
        self.history("UPDATE thread_turns SET started_at=?", (NOW - 500,))
        self.write(record(NOW - 240, "response_item", type="reasoning", summary=[]), record(NOW - 2, "event_msg", type="stream_error", turn_id="turn", message="stream disconnected - retrying sampling request"))
        task = self.task()
        self.assertEqual(task["silenceSeconds"], 2)
        self.assertEqual(task["health"]["silenceSeconds"], 240)
        self.assertEqual(task["health"]["level"], "watch")
        self.assertIn("连接重试", task["health"]["label"])
        self.write(record(NOW - 1, "event_msg", type="item_completed", turn_id="turn", item={"type": "Reasoning", "id": "resumed"}))
        self.assertEqual(self.task()["health"]["level"], "active")

    def test_log_without_turn_identity_cannot_implicate_current_turn(self):
        with sqlite3.connect(str(self.home / "logs_2.sqlite")) as conn:
            conn.execute("INSERT INTO logs VALUES (?,?,?,?,?,?)", ("thread", NOW - 1, 0, "WARN", "codex_core::responses_retry", "stream disconnected - retrying sampling request"))
        self.assertEqual(self.task()["networkErrors"], [])

    def test_other_turn_compaction_is_ignored_even_with_overlapping_time(self):
        self.write(record(NOW - 5, "event_msg", type="item_started", turn_id="old-turn", item={"type": "ContextCompaction", "id": "old"}))
        task = self.task()
        self.assertNotEqual(task["stage"]["code"], "compacting")
        self.assertIsNone(task["health"]["lastProgressAt"])

    def test_future_records_do_not_fabricate_progress(self):
        self.write(record(NOW + 60, "response_item", type="reasoning", summary=[]), record(NOW - 2, "event_msg", type="item_started", item={"type": "ContextCompaction", "id": "bad"}, started_at_ms=(NOW + 60) * 1000))
        task = self.task()
        self.assertIsNone(task["health"]["lastProgressAt"])
        self.assertNotEqual(task["stage"]["code"], "compacting")

    def test_terminal_status_does_not_remain_compacting(self):
        self.write(record(NOW - 20, "event_msg", type="compaction_started", turn_id="turn"), record(NOW - 5, "event_msg", type="task_completed", turn_id="turn"))
        task = self.task()
        self.assertEqual(task["stage"]["code"], "idle")
        self.assertEqual(task["health"]["level"], "idle")

    def test_usage_sample_preserves_reasoning_and_compaction_stage(self):
        self.write(record(NOW - 5, "response_item", type="reasoning", summary=[]), record(NOW - 4, "token_usage_record", turn_id="turn", turn_token_usage={"output_tokens": 10}))
        self.assertEqual(self.task()["stage"]["code"], "reasoning")
        self.write(record(NOW - 3, "compacted", message="private"), record(NOW - 2, "token_usage_record", turn_id="turn", turn_token_usage={"output_tokens": 20}))
        self.assertEqual(self.task()["stage"]["code"], "compacted")

    def test_failed_tool_completion_is_not_healthy_progress(self):
        self.write(record(NOW - 5, "event_msg", type="item_completed", turn_id="turn", item={"type": "CommandExecution", "id": "failed", "status": "failed"}))
        task = self.task()
        self.assertIsNone(task["health"]["lastProgressAt"])
        self.assertEqual(task["health"]["level"], "watch")

    def test_no_first_progress_over_two_minutes_requires_attention(self):
        self.history("UPDATE thread_turns SET started_at=?", (NOW - 500,))
        task = self.task()
        self.assertIsNone(task["health"]["lastProgressAt"])
        self.assertEqual(task["health"]["level"], "watch")

    def test_counter_write_is_not_a_heartbeat_or_connection_recovery(self):
        self.write(record(NOW - 5, "event_msg", type="stream_error", turn_id="turn", message="stream disconnected - retrying sampling request"), record(NOW - 1, "token_usage_record", turn_id="turn", turn_token_usage={"output_tokens": 100}))
        task = self.task()
        self.assertIsNone(task["health"]["lastProgressAt"])
        self.assertEqual(task["diagnosis"]["code"], "connection_retry")
        self.assertEqual(task["health"]["level"], "watch")

    def test_subagent_title_uses_metadata_fallback_without_prompt(self):
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as conn:
            for column in ("agent_nickname", "agent_path", "agent_role", "first_user_message"):
                conn.execute("ALTER TABLE threads ADD COLUMN " + column + " TEXT")
            conn.execute("UPDATE threads SET name='',title=' ',agent_nickname=?,agent_path=?,agent_role=?,first_user_message=?", ("Helmholtz", "/root/collector", "reviewer", "PRIVATE TASK PROMPT"))
            conn.execute("INSERT INTO thread_spawn_edges VALUES (?,?)", ("parent-thread", "thread"))
        task = self.task()
        self.assertEqual(task["title"], "子任务 · Helmholtz")
        self.assertEqual(task["agentPath"], "/root/collector")
        self.assertEqual(task["agentRole"], "reviewer")
        self.assertEqual(task["parentId"], "parent-thread")
        self.assertNotIn("PRIVATE TASK PROMPT", json.dumps(task))
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET agent_nickname=NULL")
        self.assertEqual(self.task()["title"], "子任务 · collector")
        with sqlite3.connect(str(self.home / "state_5.sqlite")) as conn:
            conn.execute("UPDATE threads SET title='明确的标题'")
        self.assertEqual(self.task()["title"], "明确的标题")


if __name__ == "__main__":
    unittest.main()
