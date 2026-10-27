#!/usr/bin/env python3
"""Exercise the shipped executable against synthetic local files, never user data."""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import select
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def create_fixture(directory: Path) -> None:
    now = int(time.time())
    rollout = directory / "rollout.jsonl"
    rollout.write_text(json.dumps({
        "timestamp": datetime.fromtimestamp(now - 2, timezone.utc).isoformat(),
        "type": "event_msg", "payload": {"type": "task_started", "turn_id": "smoke-turn"},
    }) + "\n")
    with sqlite3.connect(directory / "state_5.sqlite") as connection:
        connection.execute("CREATE TABLE threads (id TEXT, rollout_path TEXT, title TEXT, name TEXT, cwd TEXT, source TEXT, model TEXT, updated_at INTEGER, archived INTEGER)")
        connection.execute("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?)", (
            "00000000-0000-4000-8000-000000000001", str(rollout), "Release fixture", None,
            "/fixture", "vscode", "fixture-model", now, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    app = args.app.resolve()
    helper = app / "Contents/Resources/backend/pulse-backend"
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    assert info.get("PulseBuildMode") == "release", "Refuse to validate a source/dev build as a release"
    assert helper.is_file(), "The release must embed pulse-backend"
    with tempfile.TemporaryDirectory(prefix="pulse-release-smoke-") as directory:
        fixture = Path(directory)
        create_fixture(fixture)
        # Explicitly exclude development Python search paths and proxies.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "PYI_")) and "proxy" not in key.lower()}
        env.update(CODEX_HOME=str(fixture), PATH="/usr/bin:/bin")
        before = {path.name: path.read_bytes() for path in fixture.iterdir()}
        sample = subprocess.run([str(helper), "monitor", "--once"], cwd=fixture,
                                env=env, capture_output=True, text=True, timeout=15, check=True)
        snapshot = json.loads(sample.stdout)
        assert len(snapshot["tasks"]) == 1 and snapshot["tasks"][0]["status"] == "running", snapshot
        assert snapshot["tasks"][0]["title"] == "Release fixture"
        native = subprocess.run([str(app / "Contents/MacOS" / info["CFBundleExecutable"]), "--self-check"],
                                cwd=fixture, env=env, capture_output=True, text=True, timeout=20, check=True)
        assert "PASS" in native.stdout, native.stdout
        process = subprocess.Popen([str(helper), "server", "--port", "0"], cwd=fixture, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready, _, _ = select.select([process.stdout], [], [], 10)
            assert ready, "Bundled dashboard did not start"
            line = process.stdout.readline()
            match = re.search(r"http://127\.0\.0\.1:\d+", line)
            assert match, "Bundled dashboard did not report its loopback URL"
            base = match.group()
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(30):
                try:
                    with client.open(base + "/api/health", timeout=2) as response:
                        health = json.load(response)
                    if health["ok"]:
                        break
                except urllib.error.HTTPError as error:
                    if error.code != 503:
                        raise
                time.sleep(0.1)
            else:
                raise AssertionError("Bundled dashboard never became healthy")
            for path in ("/", "/app.js", "/styles.css"):
                with client.open(base + path, timeout=2) as response:
                    assert response.status == 200 and len(response.read()) > 100
            with client.open(base + "/api/snapshot", timeout=2) as response:
                assert json.load(response)["tasks"][0]["title"] == "Release fixture"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
        after = {path.name: path.read_bytes() for path in fixture.iterdir()}
        assert before == after, "A release smoke check changed its read-only fixture"
    print("PASS: bundled monitor, native decoder, dashboard assets/API, read-only fixture")


if __name__ == "__main__":
    main()
