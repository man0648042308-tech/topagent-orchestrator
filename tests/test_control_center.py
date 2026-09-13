from __future__ import annotations

import json
import threading
import unittest
from urllib.request import urlopen

from topagent.api.server import create_server
from tests.helpers import TempWorkspace


class ControlCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempWorkspace()
        self.server = create_server(port=0, database=self.temp.db)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temp.close()

    def get_json(self, path):
        with urlopen(self.base + path, timeout=3) as response:
            return json.loads(response.read())

    def test_health_metrics_and_dashboard(self):
        health = self.get_json("/api/health")
        self.assertTrue(health["ok"])
        metrics = self.get_json("/api/metrics")
        self.assertIn("executions", metrics)
        with urlopen(self.base + "/", timeout=3) as response:
            html = response.read().decode("utf-8")
        self.assertIn("TopAgent Control Center", html)


if __name__ == "__main__":
    unittest.main()
