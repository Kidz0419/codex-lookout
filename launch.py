#!/usr/bin/env python3
"""Start/reuse this app, open its local page, and keep a visible stop control."""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from collector import Collector
from server import SnapshotStore

URL = 'http://127.0.0.1:4318'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def is_our_server():
    try:
        with opener.open(URL + '/api/health', timeout=1) as response:
            health = json.load(response)
            expected = SnapshotStore(Collector(Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))), limit=80)).source_id
            return health.get('service') == 'codex-lookout' and health.get('sourceId') == expected
    except (OSError, ValueError, urllib.error.URLError):
        return False


def main():
    if is_our_server():
        webbrowser.open(URL)
        return 0
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('server.py'))])
    try:
        for _ in range(40):
            if process.poll() is not None:
                return process.returncode
            if is_our_server():
                webbrowser.open(URL)
                break
            time.sleep(0.25)
        else:
            print('服务仍在初始化，可稍后打开 ' + URL, flush=True)
        return process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0


if __name__ == '__main__':
    sys.exit(main())
