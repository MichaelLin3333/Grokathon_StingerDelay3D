import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from server.main import Handler


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def fetch(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_api_alias(self):
        status, data = self.fetch('/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(data['ok'])
        self.assertEqual(data['mode'], 'replay')

    def test_full_plan_and_grok(self):
        status, trace = self.fetch('/api/trips/plan', {'origin':'student-center','destination':'klaus'})
        self.assertEqual(status, 200)
        self.assertTrue(trace['verified'])
        status, chat = self.fetch('/grok/chat', {'message':'When should I leave?', 'trace':trace})
        self.assertEqual(status, 200)
        self.assertTrue(chat['verified'])
        self.assertIn('Klaus', chat['reply'])

    def test_calendar_schedule(self):
        status, data = self.fetch('/calendar/events')
        self.assertEqual(status, 200)
        self.assertEqual(data['mode'], 'demo')
        status, schedule = self.fetch('/schedule', {'origin':'student-center'})
        self.assertEqual(status, 200)
        self.assertEqual(len(schedule['items']), 3)

    def test_invalid_and_cross_origin(self):
        status, _ = self.fetch('/trips/plan', {})
        self.assertEqual(status, 422)
        status, data = self.fetch('/trips/plan', {'origin':'no-location','destination':'klaus'})
        self.assertEqual(status, 422)
        status, _ = self.fetch('/trips/plan', {'origin':'student-center','destination':'klaus'}, {'Origin':'https://evil.example'})
        self.assertEqual(status, 403)

    def test_contracts_available(self):
        status, schema = self.fetch('/contracts/trip-trace.json')
        self.assertEqual(status, 200)
        self.assertEqual(schema['title'], 'TripTrace v0')
        status, openapi = self.fetch('/openapi.json')
        self.assertEqual(status, 200)
        self.assertEqual(openapi['openapi'], '3.1.0')

    def test_unknown_api_endpoint(self):
        status, _ = self.fetch('/api/not-found')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
