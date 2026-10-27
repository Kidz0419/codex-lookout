#!/usr/bin/env python3
"""Emit read-only Codex task snapshots as JSONL for the native status widget.

Each successful line has the Collector.snapshot schema.  A failed sample emits
type=collectorError, leaving the native client free to retain its last snapshot.
No prompts, command arguments, raw errors or log bodies are printed here.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


def _load_collector():
    # Packaged: Resources/backend/{monitor,collector}.py.
    # Checkout: native/monitor.py with ../collector.py.
    here = Path(__file__).resolve().parent
    for directory in (here, here.parent):
        if (directory / "collector.py").is_file():
            sys.path.insert(0, str(directory))
            from collector import Collector
            return Collector
    raise ImportError("Collector module unavailable")


def _error_record(exc: Exception) -> dict[str, Any]:
    return {
        "type": "collectorError",
        "message": "本地任务采集暂时不可用，正在等待下一次采样。",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "errorType": type(exc).__name__,
    }


def _write_line(value: dict, stream: TextIO) -> bool:
    """Flush a whole sample; a closed native-client pipe ends the helper quietly."""
    try:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        stream.flush()
        return True
    except BrokenPipeError:
        # Prevent a second BrokenPipeError during Python's shutdown flush.
        try:
            stream.close()
        except (BrokenPipeError, OSError):
            pass
        return False


def _positive_interval(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("interval must be a positive number")
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("interval must be a positive finite number")
    return parsed


def _task_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 500")
    if not 1 <= parsed <= 500:
        raise argparse.ArgumentTypeError("limit must be an integer from 1 to 500")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Codex task snapshot stream (JSONL)")
    parser.add_argument("--interval", type=_positive_interval, default=2.0, help="seconds between samples (default: 2)")
    parser.add_argument("--limit", type=_task_limit, default=200, help="recent local tasks, 1–500 (default: 200)")
    parser.add_argument("--once", action="store_true", help="emit one sample and exit")
    args = parser.parse_args(argv)
    home = Path(os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")).expanduser()
    collector = None
    try:
        while True:
            started = time.monotonic()
            try:
                if collector is None:
                    collector = _load_collector()(home, limit=args.limit)
                sample = collector.snapshot()
                # Validate serialization inside the failure boundary as well.
                json.dumps(sample, allow_nan=False)
            except Exception as exc:
                sample = _error_record(exc)
            if not _write_line(sample, sys.stdout):
                return 0
            if args.once:
                return 0
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
