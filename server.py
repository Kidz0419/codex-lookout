#!/usr/bin/env python3
"""Codex Lookout: a loopback-only, read-only view of local Codex telemetry."""
import argparse
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from collector import Collector

ROOT = Path(__file__).resolve().parent


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace('+00:00', 'Z')


def demo_snapshot():
    """Explicit synthetic scenarios; never blended into the live task list."""
    now = time.time()
    specs = [
        ('demo-network', '检查部署后的接口', 'model', 85, 35, 'network_error', '连接正在重试', 'warning', 'observed', '本轮请求记录了连接中断与重试；不能据此区分本地网络和上游服务。', '检查代理与网络状态；先观察下一次重试结果。'),
        ('demo-tool', '运行完整测试套件', 'tool', 480, 4, 'tool_running', '长任务仍有活动', 'ok', 'observed', '本轮已执行 8 分钟，最近 4 秒前又调用了工具。能确认有新活动，工具内部进度需回到任务查看。', '继续观察；打开任务查看测试输出。'),
        ('demo-silent', '分析项目依赖关系', 'model', 620, 310, 'silent', '长时间无新事件', 'warning', 'inferred', '已 5 分钟没有新的落盘事件。可能仍在思考，也可能在等待或停滞，尚不能确认。', '回到任务查看当前提示，再决定继续等待或中断。'),
        ('demo-done', '修复表单校验', 'idle', 74, 24, 'completed', '已完成', 'ok', 'observed', '已收到本轮完成事件。', '可回到 Codex 查看结果。'),
    ]
    tasks = []
    for ident, title, phase, elapsed, silence, code, label, severity, confidence, summary, action in specs:
        start = now - elapsed
        end = now - silence if ident == 'demo-done' else None
        events = [
            {'at': iso(start), 'kind': 'turn', 'label': '本轮开始'},
            {'at': iso(start + 3), 'kind': 'model', 'label': '模型活动'},
            {'at': iso(now - silence), 'kind': 'tool' if phase == 'tool' else 'model', 'label': '调用 exec_command' if phase == 'tool' else '最近活动'},
        ]
        network = []
        if code == 'network_error':
            network = [{'at': iso(now - silence), 'kind': 'retry', 'label': '连接中断后重试（示例）'}]
            events[-1] = dict(network[0])
        if end:
            events[-1] = {'at': iso(end), 'kind': 'completed', 'label': '本轮完成'}
        tasks.append({
            'id': ident, 'title': title, 'cwd': '/示例项目', 'model': '示例模型', 'parentId': None,
            'updatedAt': iso(now - silence), 'lastEventAt': iso(now - silence),
            'turnStartedAt': iso(start), 'turnEndedAt': iso(end) if end else None,
            'status': 'completed' if end else 'running', 'phase': phase,
            'elapsedSeconds': elapsed - silence if end else elapsed, 'silenceSeconds': silence,
            'diagnosis': dict(code=code, label=label, severity=severity, confidence=confidence, summary=summary, action=action),
            'currentTool': {'name': 'exec_command', 'startedAt': iso(now - silence), 'elapsedSeconds': silence} if phase == 'tool' else None,
            'tokens': {'output': 2600, 'reasoning': 1200, 'total': 18200, 'lastSampleAt': iso(now - silence), 'rate': None, 'rateLabel': '无逐 token 时间戳'},
            'events': events, 'networkErrors': network,
            'activity': [{'at': e['at'], 'count': 1} for e in events],
            'coverage': {'complete': True, 'note': '演示数据，用于说明诊断状态'},
        })
    return {'generatedAt': iso(now), 'demo': True, 'tasks': tasks,
            'sources': [{'name': '演示数据', 'available': True, 'note': '合成案例，不代表你的任务'}],
            'limitations': ['本页是合成案例，切换到实时数据可查看本机任务。']}


class SnapshotStore:
    def __init__(self, collector, interval=3):
        self.collector = collector
        home = getattr(collector, 'home', None)
        key = str(Path(home).resolve()) + '\n' + str(collector.limit) if home is not None else ''
        self.source_id = hashlib.sha256(key.encode()).hexdigest()
        self.interval = interval
        self.lock = threading.Lock()
        self.value = None
        self.error = None
        self.stop = threading.Event()

    def collect(self):
        while not self.stop.is_set():
            try:
                value = self.collector.snapshot()
                value['demo'] = False
                with self.lock:
                    self.value, self.error = value, None
            except Exception as exc:
                # Do not return exception bodies: they can contain source paths/content.
                with self.lock:
                    self.error = type(exc).__name__
            self.stop.wait(self.interval)

    def get(self):
        with self.lock:
            if self.value is None:
                return 503, {'error': '正在读取本机任务，请稍后重试。', 'loading': self.error is None}
            value = dict(self.value)
            if self.error:
                value['collectorError'] = '采集失败，显示上一次快照；请检查本地数据源。'
            return 200, value


def handler_for(store):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'CodexLookout/0.1'

        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, mime='application/json; charset=utf-8'):
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def json(self, status, obj):
            self.send(status, json.dumps(obj, ensure_ascii=False, allow_nan=False).encode())

        def do_GET(self):
            # Reject DNS rebinding and cross-site fetches of private task metadata.
            port = self.server.server_port
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if self.headers.get('Host', '') not in allowed:
                return self.json(403, {'error': '仅支持本机地址访问。'})
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://{host}' for host in allowed}:
                return self.json(403, {'error': '拒绝跨站读取。'})
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return self.json(403, {'error': '拒绝跨站读取。'})
            path = urlsplit(self.path).path
            if path == '/api/snapshot':
                return self.json(*store.get())
            if path == '/api/demo':
                return self.json(200, demo_snapshot())
            if path == '/api/health':
                status, snapshot = store.get()
                return self.json(status, {'service': 'codex-lookout', 'sourceId': store.source_id, 'ok': status == 200 and not snapshot.get('collectorError'), 'generatedAt': snapshot.get('generatedAt')})
            assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/index.html': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
            if path not in assets:
                return self.json(404, {'error': '未找到资源。'})
            name, mime = assets[path]
            try:
                body = (ROOT / 'static' / name).read_bytes()
            except OSError:
                return self.json(503, {'error': '界面文件暂不可用。'})
            self.send(200, body, mime)

    return Handler


def main():
    parser = argparse.ArgumentParser(description='只读查看本机 Codex 任务状态')
    parser.add_argument('--port', type=int, default=4318)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    parser.add_argument('--limit', type=int, default=80, help='最近任务上限，默认 80')
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error('--limit 必须介于 1 和 500 之间')
    store = SnapshotStore(Collector(args.codex_home, limit=args.limit))
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(store))
    except OSError as exc:
        parser.exit(1, f'无法启动本地面板（{exc.strerror}）。可使用 --port 指定其他端口。\n')
    thread = threading.Thread(target=store.collect, daemon=True)
    thread.start()
    print(f'Codex Lookout → http://127.0.0.1:{server.server_port}', flush=True)
    print('本机只读监测；按 Ctrl+C 停止。', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        store.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
