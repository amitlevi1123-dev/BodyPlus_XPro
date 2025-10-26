# -*- coding: utf-8 -*-
"""
בדיקת Smoke כללית — מאמתת שכל השירותים המרכזיים עולים ונותנים תגובה תקינה.
--------------------------------------------------------------
בדיקה זו לא בוחנת לוגיקה, רק זמינות (HTTP 200 / JSON תקין).
ניתן להריץ אותה בכל שלב כדי לוודא שהשרת רץ כמו שצריך.
"""

import unittest
import json
from admin_web.server import create_app


class TestSmokeEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.testing = True
        cls.client = app.test_client()

    def _check_json_ok(self, url: str, method: str = "get", data=None):
        func = getattr(self.client, method.lower())
        resp = func(url, json=data or {})
        self.assertIn(resp.status_code, (200, 204), msg=f"{url} → {resp.status_code}")
        if resp.data:
            try:
                payload = json.loads(resp.data.decode("utf-8"))
                self.assertIsInstance(payload, dict)
                return payload
            except Exception as e:
                self.fail(f"{url} → תגובה לא בפורמט JSON ({e})")
        return {}

    # --- Smoke tests for main routes ---
    def test_version(self):
        self._check_json_ok("/version")

    def test_healthz(self):
        self._check_json_ok("/healthz")

    def test_readyz(self):
        self._check_json_ok("/readyz")

    def test_payload(self):
        self._check_json_ok("/payload")

    def test_metrics(self):
        self._check_json_ok("/api/metrics")

    def test_session_status(self):
        self._check_json_ok("/api/session/status")

    def test_exercise_diag(self):
        self._check_json_ok("/api/exercise/diag")

    def test_exercise_simulate(self):
        self._check_json_ok("/api/exercise/simulate", method="post", data={"sets": 1, "reps": 2})

    def test_exercise_score(self):
        self._check_json_ok("/api/exercise/score", method="post", data={"metrics": {}})

    def test_logs_api(self):
        self._check_json_ok("/api/logs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
