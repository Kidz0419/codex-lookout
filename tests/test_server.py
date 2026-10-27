import importlib.util
import json
import hashlib
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import SnapshotStore, demo_snapshot, handler_for


class FakeCollector:
    def snapshot(self):
        return {'tasks': [], 'generatedAt': '2026-10-27T00:00:00Z'}


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = SnapshotStore(FakeCollector())
        cls.store.value = FakeCollector().snapshot()
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(cls.store))
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, headers=None):
        connection = HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=2)
        connection.request('GET', path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response, body

    def test_health_has_product_and_safe_source_identity(self):
        status, _, body = self.get('/api/health')
        health = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(health['service'], 'codex-lookout')
        self.assertEqual(health['sourceId'], hashlib.sha256(b'').hexdigest())
        self.assertNotIn('home', health)

    def test_source_identity_distinguishes_directory_and_task_limit(self):
        class Source:
            home = Path('/synthetic/codex-one')
            limit = 200
        first = SnapshotStore(Source()).source_id
        Source.home = Path('/synthetic/codex-two')
        second = SnapshotStore(Source()).source_id
        Source.limit = 100
        third = SnapshotStore(Source()).source_id
        self.assertEqual(len({first, second, third}), 3)
        self.assertTrue(all(len(value) == 64 for value in (first, second, third)))

    def test_live_snapshot_no_cache_no_cors(self):
        status, headers, body = self.get('/api/snapshot')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['tasks'], [])
        self.assertEqual(headers.getheader('Cache-Control'), 'no-store')
        self.assertIsNone(headers.getheader('Access-Control-Allow-Origin'))

    def test_host_rebinding_rejected(self):
        self.assertEqual(self.get('/api/snapshot', {'Host': 'evil.example'})[0], 403)

    def test_cross_site_read_rejected(self):
        self.assertEqual(self.get('/api/snapshot', {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.get('/api/snapshot', {'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_no_arbitrary_file_read(self):
        for path in ['/../collector.py', '/%2e%2e/collector.py', '/auth.json', '/server.py']:
            self.assertEqual(self.get(path)[0], 404)

    def test_demo_distinct_and_explicit(self):
        status, _, body = self.get('/api/demo')
        demo = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(demo['demo'])
        self.assertEqual(len(demo['tasks']), 4)
        self.assertTrue(all(t['id'].startswith('demo-') for t in demo['tasks']))
        self.assertTrue(all(t['tokens']['rate'] is None for t in demo['tasks']))

    def test_stale_snapshot_reports_error(self):
        self.store.error = 'OSError'
        try:
            status, _, body = self.get('/api/snapshot')
            self.assertEqual(status, 200)
            self.assertIn('collectorError', json.loads(body))
            self.assertFalse(json.loads(self.get('/api/health')[2])['ok'])
        finally:
            self.store.error = None

    def test_initial_loading_is_unavailable(self):
        value = self.store.value
        self.store.value = None
        try:
            self.assertEqual(self.get('/api/snapshot')[0], 503)
        finally:
            self.store.value = value


if __name__ == '__main__':
    unittest.main()
