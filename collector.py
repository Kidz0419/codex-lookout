"""Read-only, evidence-based monitoring of Codex's local task history.

This module intentionally never exposes message text, command arguments, tool
output, log bodies, credentials, or configuration.  It does not inspect or
control Codex processes.  SQLite connections use mode=ro and query_only.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TAIL_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 2400
SILENCE_WARNING = 120
STALE_AFTER = 15 * 60
TERMINAL = {"completed", "failed", "interrupted"}
WAIT_TOOLS = {"wait", "wait_agent", "wait_threads", "sleep", "request_user_input", "request_user_input_async", "request_onboarding_input", "request_environment_input"}
TOOL_TYPES = {"commandExecution", "mcpToolCall", "dynamicToolCall", "webSearch", "imageGeneration", "fileChange", "collabAgentToolCall", "collabToolCall"}
TRANSPORT_TARGETS = {
    "codex_core::responses_retry", "codex_core::client",
    "codex_api::endpoint::responses_websocket", "codex_api::endpoint::responses",
    "codex_api::sse::responses", "codex_client::default_client",
}
LIMITATIONS = [
    "本地历史不是逐 token 的实时流；不把落盘间隔换算成 token/s，也不能据此测量网络延迟。",
    "执行中来自最新轮次记录；超过 15 分钟没有活动的未结束轮次标记为状态未知，不断言卡死或仍在运行。",
    "只有能关联到当前轮次的明确连接或重试错误才显示为连接异常；没有错误记录不代表网络正常。",
    "工具启动和返回事件能说明等待位置，但无法证明工具内部进度；静默时间仅用于提示检查。",
    "仅读取本机未归档任务，默认最近 80 个；远程任务、其他账户以及尚未落盘的活动可能不可见。",
]


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000 if value > 100_000_000_000 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (ValueError, OverflowError):
            return None
    return None


def _iso(value: float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _status(value: Any) -> str:
    return {
        "inProgress": "running", "in_progress": "running", "running": "running",
        "completed": "completed", "complete": "completed", "succeeded": "completed",
        "failed": "failed", "error": "failed", "errored": "failed",
        "interrupted": "interrupted", "aborted": "interrupted", "cancelled": "interrupted", "canceled": "interrupted",
    }.get(value, "unknown")


def _safe_tool(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:/-]{0,120}", value):
        return value
    return "工具调用"


def _tool_name(payload: dict) -> str:
    name = _safe_tool(payload.get("name") or payload.get("tool") or payload.get("type"))
    # Extract identifiers only, never the code, commands, arguments or output.
    if name == "exec" and isinstance(payload.get("input"), str):
        found = re.findall(r"\btools\.([A-Za-z_][A-Za-z0-9_]{0,100})\s*\(", payload["input"])
        if found:
            name = " / ".join(dict.fromkeys(found[:3]))
    return name


def _network_kind(body: Any) -> tuple[str, str] | None:
    if not isinstance(body, str):
        return None
    # Tracing spans may include tool arguments before the actual log message.
    message = body.rsplit("}: ", 1)[-1].lower()
    if "falling back to http" in message:
        return "fallback", "WebSocket 连接降级为 HTTP"
    if re.search(r"\b429\b|rate.?limit", message):
        return "service_limit", "服务端限流记录"
    if re.search(r"\b40[13]\b|unauthorized|forbidden|authentication", message):
        return "service_access", "服务端拒绝连接"
    if "retrying sampling request" in message or "stream disconnected" in message:
        return "stream_retry", "模型响应流中断 / 重试"
    if "timed out" in message or "timeout" in message:
        return "timeout", "连接或请求超时"
    if any(x in message for x in ("tls handshake", "certificate", "connection reset", "broken pipe", "failed to connect to websocket", "websocket closed", "connection closed", "failed to lookup", "dns error", "error sending request", "error decoding response body")):
        return "connection", "连接传输错误"
    return None


def _event(at: float, kind: str, label: str, **extra: Any) -> dict:
    return {"at": at, "kind": kind, "label": label, **extra}


def _item_kind(value: Any) -> str:
    # Persisted rollout items use PascalCase; the history projection uses camelCase.
    return value[:1].lower() + value[1:] if isinstance(value, str) else ""


def _normalise(raw: dict) -> dict | None:
    """Discard sensitive payloads immediately; cache only safe metadata."""
    at = _seconds(raw.get("timestamp"))
    payload = raw.get("payload")
    if at is None or not isinstance(payload, dict):
        return None
    outer, kind = raw.get("type"), payload.get("type")
    if outer == "compacted":
        # The payload contains replacement conversation history. Never retain it.
        return _event(at, "context_done", "上下文压缩已完成")
    if outer == "event_msg":
        if kind in {"task_started", "turn_started"}:
            return _event(at, "start", "轮次开始", turn=payload.get("turn_id"), start=_seconds(payload.get("started_at")) or at)
        end = {"task_complete": "completed", "task_completed": "completed", "turn_completed": "completed", "turn_aborted": "interrupted", "task_aborted": "interrupted", "task_failed": "failed", "turn_failed": "failed"}.get(kind)
        if end:
            return _event(at, "end", {"completed": "轮次完成", "interrupted": "轮次中断", "failed": "轮次失败"}[end], status=end, turn=payload.get("turn_id"))
        if kind in {"error", "stream_error"}:
            error = payload.get("message") or payload.get("error")
            if isinstance(error, dict):
                error = error.get("message")
            matched = _network_kind(error)
            return _event(at, "network" if matched else "error", matched[1] if matched else "运行错误记录", errorKind=matched[0] if matched else "runtime", turn=payload.get("turn_id"))
        if kind in {"item_started", "item_completed"} and isinstance(payload.get("item"), dict):
            item = payload["item"]
            it = _item_kind(item.get("type"))
            start = _seconds(payload.get("started_at_ms"))
            end = _seconds(payload.get("completed_at_ms"))
            if it in TOOL_TYPES:
                name = _safe_tool(item.get("tool") or it)
                label = "工具启动：" if kind == "item_started" else "工具完成："
                if item.get("status") == "failed":
                    label = "工具失败："
                return _event(at, "item_tool", label + name, key=item.get("id"), tool=name, start=start, end=end, eventState=kind, status=item.get("status"), turn=payload.get("turn_id"), durationSeconds=round(max(0, (end - start)), 2) if end and start and end > start else None)
            if it == "contextCompaction":
                finished = kind == "item_completed" or end is not None
                return _event(at, "context_done" if finished else "context_start", "上下文压缩已完成" if finished else "上下文压缩开始", key=item.get("id"), start=start, end=end, turn=payload.get("turn_id"), durationSeconds=round(max(0, end - start), 2) if end is not None and start is not None else None)
            if it in {"reasoning", "agentMessage", "subAgentActivity"}:
                return _event(at, "model" if it != "subAgentActivity" else "agent", {"reasoning": "推理记录已更新", "agentMessage": "助手输出已记录", "subAgentActivity": "子任务活动"}[it], key=item.get("id"), modelKind=it, turn=payload.get("turn_id"))
        if kind == "token_count":
            # Legacy token_count totals are thread-wide; never mislabel as this turn.
            return _event(at, "token_sample", "Token 统计已落盘")
        if kind in {"agent_message", "agent_reasoning"}:
            return _event(at, "model", "助手输出已记录" if kind == "agent_message" else "推理记录已更新", modelKind="agentMessage" if kind == "agent_message" else "reasoning", turn=payload.get("turn_id"))
        if kind in {"context_compacted", "compaction_started", "compaction_completed"}:
            begun = kind == "compaction_started"
            return _event(at, "context_start" if begun else "context_done", "上下文压缩开始" if begun else "上下文压缩已完成", turn=payload.get("turn_id"))
    if outer == "response_item":
        if kind in {"function_call", "custom_tool_call"}:
            name = _tool_name(payload)
            return _event(at, "tool_start", "调用 " + name, key=payload.get("call_id") or payload.get("id"), tool=name)
        if kind in {"function_call_output", "custom_tool_call_output"}:
            output = payload.get("output")
            # Only the exact orchestration envelope is a yield, never prose stdout.
            yielded = isinstance(output, str) and bool(re.match(r"^Script running with cell ID [A-Za-z0-9_-]+", output))
            return _event(at, "tool_end", "工具返回" if not yielded else "工具已交回异步等待", key=payload.get("call_id") or payload.get("id"), yielded=yielded)
        if kind == "reasoning":
            return _event(at, "model", "推理记录已更新", key=payload.get("id"), modelKind="reasoning")
        if kind == "message" and payload.get("role") == "assistant":
            return _event(at, "model", "助手输出已记录", key=payload.get("id"), modelKind="agentMessage")
    if outer == "token_usage_record":
        usage = payload.get("turn_token_usage")
        if isinstance(usage, dict):
            clean = {k: usage.get(k) if isinstance(usage.get(k), (int, float)) else None for k in ("output_tokens", "reasoning_output_tokens", "total_tokens")}
            return _event(at, "tokens", "本轮 Token 统计已更新", turn=payload.get("turn_id"), usage=clean)
    return None


class Collector:
    """Collect local metadata. ``home`` is ~/.codex, or a home containing it."""

    def __init__(self, home: Path | str, limit: int = 80):
        base = Path(home).expanduser()
        self.home = base / ".codex" if (base / ".codex").is_dir() else base
        self.limit = max(1, min(500, int(limit)))
        self._cache: dict[str, dict] = {}
        self._lock = threading.RLock()

    def _connect(self, name: str, sources: list) -> sqlite3.Connection | None:
        path = self.home / name
        if not path.is_file():
            sources.append({"name": name, "available": False, "note": "数据文件不存在"})
            return None
        try:
            conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.3)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            sources.append({"name": name, "available": True, "note": "只读连接"})
            return conn
        except (sqlite3.Error, OSError) as exc:
            sources.append({"name": name, "available": False, "note": "无法读取：" + type(exc).__name__})
            return None

    @staticmethod
    def _source_error(sources: list, name: str, exc: Exception) -> None:
        for source in sources:
            if source["name"] == name:
                source.update(available=False, note="读取失败：" + type(exc).__name__)

    def _read_rollout(self, path: str, turn: dict | None) -> tuple[list, bool, str]:
        p = Path(path).expanduser()
        try:
            stat = p.stat()
            key = str(p)
            turn_id = turn.get("turn_id") if turn else None
            boundary = turn.get("rollout_byte_offset") if turn else None
            boundary = int(boundary) if isinstance(boundary, int) and 0 <= boundary <= stat.st_size else 0
            cache = self._cache.get(key)
            if not cache or cache["inode"] != stat.st_ino or cache["offset"] > stat.st_size or cache["turn"] != turn_id:
                offset = max(boundary, stat.st_size - TAIL_BYTES)
                cache = {"inode": stat.st_ino, "offset": offset, "turn": turn_id, "records": [], "complete": offset == boundary, "bad": False, "partial": offset > boundary, "mtime": None}
                self._cache[key] = cache
            if cache["mtime"] == stat.st_mtime_ns and cache["offset"] == stat.st_size:
                return list(cache["records"]), cache["complete"] and not cache["bad"], ""
            with p.open("rb") as stream:
                # A large burst between polls is bounded too; the gap is visible.
                if stat.st_size - cache["offset"] > TAIL_BYTES:
                    cache.update(offset=stat.st_size - TAIL_BYTES, complete=False, partial=True)
                    cache["records"] = []
                stream.seek(cache["offset"])
                if cache["partial"]:
                    stream.readline()
                    cache["partial"] = False
                start = stream.tell()
                chunk = stream.read(TAIL_BYTES)
                last_newline = chunk.rfind(b"\n")
                if last_newline >= 0:
                    for line in chunk[:last_newline + 1].splitlines():
                        try:
                            data = json.loads(line)
                            event = _normalise(data) if isinstance(data, dict) else None
                            if event:
                                cache["records"].append(event)
                        except (ValueError, TypeError, AttributeError):
                            cache["bad"] = True
                    cache["offset"] = start + last_newline + 1
            if len(cache["records"]) > MAX_RECORDS:
                cache["records"] = cache["records"][-MAX_RECORDS:]
                cache["complete"] = False
            cache["mtime"] = stat.st_mtime_ns
            return list(cache["records"]), cache["complete"] and not cache["bad"], "部分记录无法解析" if cache["bad"] else ""
        except (OSError, ValueError) as exc:
            return [], False, "运行记录不可读：" + type(exc).__name__

    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        with self._lock:
            sources: list[dict] = []
            state = self._connect("state_5.sqlite", sources)
            history = self._connect("thread_history_1.sqlite", sources)
            logs = self._connect("logs_2.sqlite", sources)
            tasks: list[dict] = []
            rollout_ok, rollout_bad = 0, 0
            try:
                rows = []
                if state:
                    try:
                        rows = [dict(row) for row in state.execute("SELECT * FROM threads WHERE archived = 0 ORDER BY updated_at DESC LIMIT ?", (self.limit,))]
                    except sqlite3.Error as exc:
                        self._source_error(sources, "state_5.sqlite", exc)
                parents = {}
                if rows and state:
                    try:
                        ids = [row["id"] for row in rows]
                        parents = dict(state.execute("SELECT child_thread_id, parent_thread_id FROM thread_spawn_edges WHERE child_thread_id IN (" + ",".join("?" for _ in ids) + ")", ids))
                    except sqlite3.Error:
                        pass  # Older versions can still link via source metadata.
                for row in rows:
                    turn = None
                    items = []
                    history_error = None
                    if history:
                        try:
                            selected = history.execute("SELECT * FROM thread_turns WHERE thread_id = ? ORDER BY rollout_ordinal DESC LIMIT 1", (row["id"],)).fetchone()
                            turn = dict(selected) if selected else None
                            if turn:
                                items = [dict(x) for x in history.execute("SELECT * FROM thread_items WHERE thread_id = ? AND turn_id = ? ORDER BY rollout_ordinal DESC LIMIT 120", (row["id"], turn["turn_id"]))]
                        except sqlite3.Error as exc:
                            history_error = type(exc).__name__
                            self._source_error(sources, "thread_history_1.sqlite", exc)
                    records, complete, note = self._read_rollout(row.get("rollout_path", ""), turn)
                    if note.startswith("运行记录不可读"):
                        rollout_bad += 1
                    else:
                        rollout_ok += 1
                    task = self._task(row, turn, items, records, complete, note, parents.get(row["id"]), now)
                    if history_error:
                        task["coverage"] = {"complete": False, "note": "历史数据库读取失败；仅使用可读的运行记录。"}
                    network = []
                    start = _seconds(task.get("turnStartedAt"))
                    end = _seconds(task.get("turnEndedAt"))
                    if logs and start:
                        try:
                            # Thread ID is mandatory; global errors never implicate a task.
                            entries = logs.execute("SELECT ts, ts_nanos, level, target, feedback_log_body FROM logs WHERE thread_id = ? AND ts >= ? AND ts <= ? AND level IN ('WARN', 'ERROR') ORDER BY ts DESC, ts_nanos DESC LIMIT 150", (row["id"], int(start), int(end or now) + 1))
                            for entry in entries:
                                if entry["target"] not in TRANSPORT_TARGETS:
                                    continue
                                body = entry["feedback_log_body"] or ""
                                tail = body.rsplit("}: ", 1)[-1]
                                pattern = r"\b(?:turn_id|turn\.id)=[\"']?([A-Za-z0-9_-]{1,160})"
                                attributed = re.findall(pattern, tail) or re.findall(pattern, body)
                                # Turns may overlap within one thread. Time alone cannot attribute a failure.
                                if not task.get("_turnId") or task["_turnId"] not in attributed:
                                    continue
                                at = float(entry["ts"]) + (entry["ts_nanos"] or 0) / 1_000_000_000
                                if at < start or (end and at > end) or at > now + 2:
                                    continue
                                match = _network_kind(body)
                                if match:
                                    network.append({"at": at, "kind": match[0], "label": match[1]})
                        except sqlite3.Error as exc:
                            self._source_error(sources, "logs_2.sqlite", exc)
                    network += task.pop("_network")
                    network.sort(key=lambda x: x["at"])
                    # Deduplicate identical local-log/rollout error records.
                    dedup = {(round(n["at"], 1), n["kind"]): n for n in network}
                    network = sorted(dedup.values(), key=lambda x: x["at"])[-12:]
                    last_model = task.pop("_lastModel")
                    task.pop("_turnId", None)
                    if network:
                        newest = network[-1]["at"]
                        previous = _seconds(task.get("lastEventAt")) or 0
                        if newest > previous:
                            task["lastEventAt"] = _iso(newest)
                            task["silenceSeconds"] = round(max(0, now - newest), 1)
                            if task["status"] == "unknown" and start:
                                task["elapsedSeconds"] = round(max(0, newest - start), 1)
                        known = {(e["at"], e["label"]) for e in task["events"]}
                        additions = [dict(at=_iso(n["at"]), kind="network", label=n["label"]) for n in network if (_iso(n["at"]), n["label"]) not in known]
                        task["events"] = sorted(task["events"] + additions, key=lambda e: e["at"])[-48:]
                        activity = {_seconds(e["at"]): e["count"] for e in task["activity"]}
                        for event in additions:
                            event_at = _seconds(event["at"])
                            if event_at is not None and now - 1800 <= event_at <= now:
                                bucket = int(event_at // 30) * 30
                                activity[bucket] = activity.get(bucket, 0) + 1
                        task["activity"] = [dict(at=_iso(at), count=count) for at, count in sorted(activity.items())]
                    task["networkErrors"] = [{**n, "at": _iso(n["at"])} for n in network]
                    task["diagnosis"] = self._diagnose(task, network, last_model, now)
                    task["health"] = self._health(task, task.pop("_lastProgress"), task.pop("_lastFailure"), now)
                    tasks.append(task)
                sources.append({"name": "sessions JSONL", "available": rollout_ok > 0, "note": f"已读取 {rollout_ok} 个运行记录；{rollout_bad} 个不可读。每个文件最多读取 2 MiB，随后增量读取。"})
                # Keep cache size bounded as recent-task selection changes.
                active_paths = {str(Path(row.get("rollout_path", "")).expanduser()) for row in rows}
                self._cache = {key: value for key, value in self._cache.items() if key in active_paths}
            finally:
                for conn in (state, history, logs):
                    if conn:
                        conn.close()
            return {"generatedAt": _iso(now), "tasks": tasks, "sources": sources, "limitations": list(LIMITATIONS), "taskLimit": self.limit}

    def _task(self, row: dict, turn: dict | None, items: list, records: list, complete: bool, note: str, parent: str | None, now: float) -> dict:
        records = [event for event in records if all(value is None or value <= now + 2 for value in (event["at"], event.get("start"), event.get("end")))]
        start = _seconds(turn.get("started_at")) if turn else None
        end = _seconds(turn.get("completed_at")) if turn else None
        status = _status(turn.get("status")) if turn else "unknown"
        turn_id = turn.get("turn_id") if turn else None
        if (start is not None and start > now + 2) or (end is not None and end > now + 2):
            start, end, status, complete = None, None, "unknown", False
        # Rollout is the source of truth if the SQL projection lags a new turn.
        starts = [e for e in records if e["kind"] == "start"]
        if starts:
            newest = starts[-1]
            newer_id = newest.get("turn") and newest.get("turn") != turn_id and newest["at"] >= (start or 0)
            newer_without_id = not newest.get("turn") and newest["at"] > (start or 0) + 1
            if not turn_id or newer_id or newer_without_id:
                start, end, status, turn_id = newest.get("start", newest["at"]), None, "running", newest.get("turn")
                items = []
            elif start is None:
                start = newest.get("start", newest["at"])
        if start:
            records = [e for e in records if e["at"] >= start - 0.01 and (end is None or e["at"] <= end + 0.01) and (not e.get("turn") or not turn_id or e["turn"] == turn_id)]
        else:
            # No known turn boundary: show safe activity but don't invent a run.
            complete = False
        pending: dict[str, dict] = {}
        events = []
        last_model = None
        network = []
        tokens = {"output": None, "reasoning": None, "total": None, "lastSampleAt": None, "rate": None, "rateLabel": "统计间歇落盘，无法测量实时 token/s", "scope": "unknown"}
        yielded = False
        for event in records:
            kind, at = event["kind"], event["at"]
            if kind == "end":
                status, end = event["status"], at
                pending.clear()
                yielded = False
            elif kind == "tool_start":
                pending[event.get("key") or str(at)] = {"name": event["tool"], "at": at}
                last_model = max(last_model or 0, at)
                yielded = False
            elif kind == "tool_end":
                pending.pop(event.get("key"), None)
                yielded = event.get("yielded", False)
            elif kind == "item_tool":
                key = event.get("key") or str(at)
                if event.get("eventState") == "item_completed" or _status(event.get("status")) in TERMINAL or event.get("end"):
                    pending.pop(key, None)
                elif event.get("eventState") == "item_started" or _status(event.get("status")) == "running":
                    pending[key] = {"name": event["tool"], "at": event.get("start") or at}
            elif kind == "model":
                last_model = max(last_model or 0, at)
                yielded = False
            elif kind == "context_done":
                last_model = max(last_model or 0, at)
                yielded = False
            elif kind == "tokens":
                usage = event["usage"]
                tokens.update(output=usage["output_tokens"], reasoning=usage["reasoning_output_tokens"], total=usage["total_tokens"], lastSampleAt=_iso(at), scope="turn")
            elif kind == "token_sample":
                tokens["lastSampleAt"] = _iso(at)
            elif kind == "network":
                if turn_id and event.get("turn") == turn_id:
                    network.append({"at": at, "kind": event["errorKind"], "label": event["label"]})
            if kind != "token_sample":
                events.append(event)
        # History items fill gaps without using NULL completion as a running flag.
        seen_keys = {e.get("key") for e in events if e.get("key")}
        for row_item in reversed(items):
            try:
                item = json.loads(row_item["item_json"])
            except (ValueError, TypeError):
                complete = False
                continue
            if not isinstance(item, dict):
                continue
            if any((_seconds(row_item.get(field)) or 0) > now + 2 for field in ("created_at_ms", "started_at_ms", "completed_at_ms")):
                continue
            at = _seconds(row_item.get("completed_at_ms")) or _seconds(row_item.get("created_at_ms"))
            if at is None or at > now + 2 or (start and at < start - 0.01) or (end and at > end + 0.01):
                continue
            kind = _item_kind(item.get("type") or row_item.get("item_type"))
            key = item.get("id")
            # Positive completion evidence wins over an unmatched raw start,
            # including older rows that have status but no completion timestamp.
            if kind in TOOL_TYPES and (_status(item.get("status")) in TERMINAL or row_item.get("completed_at_ms")):
                pending.pop(key, None)
            if kind == "contextCompaction":
                item_start, item_end = _seconds(row_item.get("started_at_ms")), _seconds(row_item.get("completed_at_ms"))
                # A timestamp-less projection row is NOT an active compaction.
                if item_end is not None:
                    events.append(_event(at, "context_done", "上下文压缩已完成", key=key, start=item_start, end=item_end, durationSeconds=round(max(0, item_end - item_start), 2) if item_start is not None else None))
                    last_model = max(last_model or 0, at)
                elif key not in seen_keys:
                    events.append(_event(at, "context_seen", "观察到压缩记录，阶段未确认", key=key))
                continue
            if key in seen_keys:
                continue
            if kind in TOOL_TYPES:
                name = _safe_tool(item.get("tool") or kind)
                item_status = _status(item.get("status"))
                if item_status == "running" and not row_item.get("completed_at_ms"):
                    pending[key or str(at)] = {"name": name, "at": _seconds(row_item.get("started_at_ms")) or at}
                label = ("工具失败：" if item_status == "failed" else "工具活动：") + name
                item_start, item_end = _seconds(row_item.get("started_at_ms")), _seconds(row_item.get("completed_at_ms"))
                duration = max(0, item_end - item_start) if item_start and item_end and item_end > item_start else None
                events.append(_event(at, "tool", label, status=item_status, durationSeconds=round(duration, 2) if duration else None))
            elif kind in {"reasoning", "agentMessage", "subAgentActivity"}:
                events.append(_event(at, "agent" if kind == "subAgentActivity" else "model", {"reasoning": "推理记录已更新", "agentMessage": "助手输出已记录", "subAgentActivity": "子任务活动"}[kind], modelKind=kind))
                if kind != "subAgentActivity":
                    last_model = max(last_model or 0, at)
        events.sort(key=lambda e: e["at"])
        last = max([e["at"] for e in records] + [e["at"] for e in events] + ([end] if end else []) + ([start] if start else []), default=None)
        silence = round(max(0, now - last), 1) if last else None
        phase = "model" if status == "running" else "idle" if status in TERMINAL else "unknown"
        current = None
        if status == "running" and pending:
            latest = max(pending.values(), key=lambda p: p["at"])
            current = {"name": latest["name"], "startedAt": _iso(latest["at"]), "elapsedSeconds": round(max(0, now - latest["at"]), 1)}
            names = re.split(r"[ /.:]+", latest["name"])
            phase = "waiting" if any(n in WAIT_TOOLS or n.endswith("__wait_threads") for n in names) else "tool"
        elif status == "running" and yielded:
            phase = "waiting"
        if status == "running" and (silence is None or silence > STALE_AFTER):
            status, phase, current = "unknown", "unknown", None
        if status in TERMINAL:
            phase, current = "idle", None
        # Persisted counters can be repeated without new model output; they are not a heartbeat.
        progress_events = [e for e in events if e["kind"] in {"model", "tool_start", "tool_end", "item_tool", "tool", "context_start", "context_done"} and _status(e.get("status")) not in {"failed", "interrupted"}]
        last_progress = max((e["at"] for e in progress_events), default=None)
        last_failure = max((e["at"] for e in events if e["kind"] == "error" or (e["kind"] in {"item_tool", "tool"} and _status(e.get("status")) == "failed")), default=None)
        stage = self._stage(status, phase, current, progress_events, now)
        if not parent:
            try:
                source = json.loads(row.get("source") or "null")
                if isinstance(source, dict):
                    parent = source.get("subagent", {}).get("thread_spawn", {}).get("parent_thread_id")
            except (ValueError, TypeError, AttributeError):
                pass
        activity = Counter(int(e["at"] // 30) * 30 for e in events if now - 1800 <= e["at"] <= now)
        event_export = []
        for e in events[-48:]:
            safe = {"at": _iso(e["at"]), "kind": e["kind"], "label": e["label"]}
            if e.get("durationSeconds") is not None:
                safe["durationSeconds"] = e["durationSeconds"]
            event_export.append(safe)
        elapsed = max(0, (end if end is not None else now) - start) if start else None
        # An unknown stale run has no defensible live duration; show the observed span.
        if status == "unknown" and start and last:
            elapsed = max(0, last - start)
        coverage_note = note or ("已读取当前轮次的可用运行记录。" if complete and start else "仅有受限尾部记录或缺少轮次边界，部分活动可能不可见。")
        title = next((value.strip() for value in (row.get("name"), row.get("title")) if isinstance(value, str) and value.strip()), None)
        agent_path = row.get("agent_path")
        agent_role = row.get("agent_role")
        if title is None:
            nickname = row.get("agent_nickname")
            agent_label = nickname.strip() if isinstance(nickname, str) and nickname.strip() else None
            if not agent_label and isinstance(agent_path, str) and agent_path.rstrip("/"):
                agent_label = agent_path.rstrip("/").rsplit("/", 1)[-1]
            title = "子任务 · " + agent_label if agent_label else "未命名任务"
        return {
            "id": row["id"], "title": title[:500], "agentPath": agent_path, "agentRole": agent_role,
            "cwd": row.get("cwd", ""), "model": row.get("model") or "unknown", "parentId": parent,
            "updatedAt": _iso(_seconds(row.get("updated_at_ms")) or _seconds(row.get("updated_at"))),
            "lastEventAt": _iso(last), "turnStartedAt": _iso(start), "turnEndedAt": _iso(end),
            "status": status, "phase": phase, "elapsedSeconds": round(elapsed, 1) if elapsed is not None else None,
            "stage": stage,
            "silenceSeconds": silence, "currentTool": current, "tokens": tokens, "events": event_export,
            "networkErrors": [], "activity": [{"at": _iso(at), "count": count} for at, count in sorted(activity.items())],
            "coverage": {"complete": bool(complete and start), "note": coverage_note},
            "_network": network, "_lastModel": last_model, "_lastProgress": last_progress, "_lastFailure": last_failure, "_turnId": turn_id,
        }

    @staticmethod
    def _stage(status: str, phase: str, current: dict | None, events: list, now: float) -> dict:
        def result(code: str, label: str, evidence: str = "observed", at: float | None = None, elapsed: float | None = None) -> dict:
            return dict(code=code, label=label, evidence=evidence, observedAt=_iso(at), elapsedSeconds=elapsed)
        if status in TERMINAL:
            return result("idle", {"completed": "本轮已完成", "failed": "本轮失败", "interrupted": "本轮已中断"}[status])
        if status == "unknown":
            return result("unknown", "当前阶段未确认", "unknown")
        # Usage counters arrive after output items; they do not change the execution stage.
        latest = max((e for e in events if e["kind"] != "tokens"), key=lambda e: e["at"], default=None)
        if latest and latest["kind"] == "context_start":
            began = latest.get("start") or latest["at"]
            return result("compacting", "压缩上下文中", at=latest["at"], elapsed=round(max(0, now - began), 1))
        if phase in {"tool", "waiting"}:
            return result(phase, "工具执行中" if phase == "tool" else "等待外部结果", at=_seconds((current or {}).get("startedAt")), elapsed=(current or {}).get("elapsedSeconds"))
        if latest and now - latest["at"] <= SILENCE_WARNING:
            if latest["kind"] == "context_done":
                return result("compacted", "最近完成上下文压缩", at=latest["at"], elapsed=latest.get("durationSeconds"))
            if latest.get("modelKind") == "reasoning":
                return result("reasoning", "最近有推理活动", at=latest["at"])
            if latest.get("modelKind") == "agentMessage":
                return result("output", "最近有助手输出", at=latest["at"])
        return result("model", "等待模型响应，阶段未确认", "unknown", latest["at"] if latest else None)

    @staticmethod
    def _health(task: dict, progress: float | None, failure: float | None, now: float) -> dict:
        silence = round(max(0, now - progress), 1) if progress is not None else None
        def result(level: str, label: str, summary: str) -> dict:
            return dict(level=level, label=label, summary=summary, lastProgressAt=_iso(progress), silenceSeconds=silence)
        status, diagnosis = task["status"], task["diagnosis"]
        if status in TERMINAL:
            return result("error" if status == "failed" else "idle", diagnosis["label"], diagnosis["summary"])
        if diagnosis["code"] == "connection_retry":
            kind = task["networkErrors"][-1]["kind"] if task["networkErrors"] else "connection"
            label = {"stream_retry": "连接重试，需关注", "service_limit": "服务限流，需关注", "service_access": "服务拒绝，需关注", "fallback": "连接降级，需关注", "timeout": "请求超时，需关注"}.get(kind, "连接异常，需关注")
            return result("watch", label, diagnosis["summary"])
        if status == "unknown":
            return result("unknown", "运行状态未确认", diagnosis["summary"])
        if failure is not None and failure > (progress or 0):
            return result("watch", "出现执行错误，需查看", "最近记录到工具失败或运行错误，之后尚未观察到新的进展；不代表整个任务已失败，请回到原会话查看。")
        if silence is not None and silence > SILENCE_WARNING:
            return result("watch", "较久无进展，需查看", "超过 2 分钟没有新的可见进展，可能是长推理、压缩、工具等待或记录延迟，不能据此确认卡死。错误与重试不计作进展。")
        if progress is None:
            started = _seconds(task.get("turnStartedAt"))
            if started is not None and now - started > SILENCE_WARNING:
                return result("watch", "等待首个进展较久", "本轮开始已超过 2 分钟，仍未观察到明确进展。无法区分模型等待、长推理、记录延迟或连接问题，请查看原会话。")
            return result("waiting", "等待进展信号", "轮次开始记录不能证明模型正在思考，尚未观察到本轮明确的推理、输出、工具或压缩进展。")
        if task["phase"] == "waiting":
            return result("waiting", "正在等待结果", "已观察到等待调用；尚不能确认外部结果何时返回。")
        return result("active", "近期有进展", "最近有推理、输出、工具或上下文压缩记录。表示观察到进展，不保证持续运行、网络畅通或最终成功。")

    @staticmethod
    def _diagnose(task: dict, network: list, last_model: float | None, now: float) -> dict:
        def result(code: str, label: str, severity: str, confidence: str, summary: str, action: str) -> dict:
            return dict(code=code, label=label, severity=severity, confidence=confidence, summary=summary, action=action)
        status, phase = task["status"], task["phase"]
        if status == "completed":
            return result("completed", "已完成", "ok", "observed", "最新轮次已有完成记录。", "无需处理。")
        if status == "interrupted":
            return result("interrupted", "已中断", "info", "observed", "最新轮次已有中断记录。", "需要继续时，回到原任务发送消息。")
        if status == "failed":
            return result("failed", "运行失败", "error", "observed", "最新轮次记录为失败。", "回到原任务检查具体错误，再决定是否重试。")
        if network and network[-1]["at"] > (last_model or 0) and now - network[-1]["at"] <= 300:
            return result("connection_retry", "连接 / 服务异常记录", "warning", "observed", "当前轮次存在明确的连接、重试或服务拒绝记录，之后尚未看到模型活动。不能据此测量网络延迟。", "在原任务检查重试进度；若持续发生，再检查网络、代理或服务状态。")
        if status == "unknown":
            return result("unknown", "状态未知", "info", "unknown", "记录不足或已长时间没有活动，无法确认任务是否仍在运行。", "打开原任务核对当前状态。")
        if task.get("stage", {}).get("code") == "compacting":
            return result("compacting", "上下文压缩中", "info", "observed", "已观察到压缩开始事件，尚未观察到完成或后续进展；这不代表压缩过程持续正常。", "结合距最近进展的时间继续观察。")
        if phase == "waiting":
            return result("waiting", "等待外部结果", "info", "observed", "当前调用是等待操作，或工具已交回异步等待；等待本身不表示卡死。", "查看原任务是否等待子任务、用户输入或外部结果。")
        if phase == "tool":
            elapsed = (task.get("currentTool") or {}).get("elapsedSeconds", 0)
            if elapsed > SILENCE_WARNING:
                return result("long_tool", "工具耗时较长", "info", "inferred", "已观察到工具启动，但尚未记录返回；无法从本地事件判断工具内部进度。", "在原任务检查该工具的输出或终端状态。")
            return result("tool_running", "正在等待工具", "ok", "observed", "最新轮次已调用工具，尚未记录返回。", "等待结果；此处显示的是调用状态。")
        if (task.get("silenceSeconds") or 0) > SILENCE_WARNING:
            return result("silent", "一段时间无新记录", "warning", "inferred", "超过 2 分钟未观察到新活动。可能是模型等待、长推理或记录未落盘，证据不足以判定卡死。", "打开原任务检查；结合连接错误与最后一次工具活动判断。")
        if network and last_model and last_model > network[-1]["at"]:
            return result("recovered", "异常后已有新活动", "ok", "observed", "本轮曾记录连接或服务异常，此后已观察到模型继续输出。", "可继续观察是否再次发生。")
        return result("active", "近期有新活动", "ok", "observed", "最新轮次尚未结束，最近仍有活动记录；当前可能在等待下一段模型输出。", "继续观察活动时间线。")
