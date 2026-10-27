#!/usr/bin/env python3
"""Write synthetic native-widget data to stdout. Never reads Codex records."""
import json
import time
from datetime import datetime, timezone

now = time.time()
def stamp(age):
    return datetime.fromtimestamp(now - age, timezone.utc).isoformat().replace('+00:00', 'Z')

def task(number, title, code, label, level, health, summary, elapsed, silence, parent=None):
    return {
        'id': f'00000000-0000-4000-8000-{number:012d}', 'title': title,
        'parentId': parent, 'status': 'running', 'phase': 'model',
        'elapsedSeconds': elapsed, 'silenceSeconds': silence,
        'updatedAt': stamp(silence), 'lastEventAt': stamp(silence), 'turnStartedAt': stamp(elapsed),
        'diagnosis': {'code': code, 'label': label, 'severity': 'ok' if level == 'active' else 'warning', 'summary': summary},
        'stage': {'code': code, 'label': label, 'evidence': 'observed', 'observedAt': stamp(silence), 'elapsedSeconds': silence},
        'health': {'level': level, 'label': health, 'summary': summary, 'lastProgressAt': stamp(silence), 'silenceSeconds': silence},
    }

build = task(1, '演示 · 为开源项目构建发布包', 'tool', '工具执行中', 'active', '近期有进展', '最近观察到工具活动。', 480, 4)
build['currentTool'] = {'name': 'exec_command', 'elapsedSeconds': 4}
compact = task(2, '演示 · 文档校对', 'compacted', '最近完成上下文压缩', 'active', '近期有进展', '观察到压缩完成事件。', 82, 9, build['id'])
network = task(3, '演示 · 检查接口响应', 'model', '等待模型活动', 'watch', '发现连接异常', '本轮观察到连接重试；仍不能区分本机网络与上游服务。', 210, 95)
print(json.dumps({'generatedAt': stamp(0), 'tasks': [build, compact, network], 'sources': [{'name': '合成演示数据', 'available': True}], 'demo': True}, ensure_ascii=False))
