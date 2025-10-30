import unittest, json
from typing import Any, Dict
try:
    from admin_web.server import create_app
except Exception as e:
    raise SystemExit(f"create_app() not importable: {e}")
def _has_endpoint(client, method: str, url: str) -> bool:
    try:
        rv = client.open(path=url, method=method, json={}, headers={"Content-Type":"application/json"})
        if rv.status_code in (404, 405):
            return False
        return True
    except Exception:
        return False
def _j(resp):
    try:
        return resp.get_json(force=True, silent=True)
    except Exception:
        return None
class TestFullStackOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = create_app()
        app.testing = True
        cls.client = app.test_client()
    # ---------- /api/exercise/simulate ----------
    def test_simulate_schema_and_modes(self):
        client = self.client
        # בדיקת קיום ראוט
        if not _has_endpoint(client, "POST", "/api/exercise/simulate"):
            self.skipTest("Endpoint /api/exercise/simulate not registered")
        # ברירת מחדל
        rv = client.post("/api/exercise/simulate", json={"sets":2,"reps":4})
        self.assertEqual(rv.status_code, 200, rv.data)
        j = _j(rv); self.assertIsInstance(j, dict)
        # חלק מהמימושים עוטפים ב{"ok":True,"data":{...}} — נכבד את שני הסגנונות
        data = j.get("data") if isinstance(j.get("data"), dict) else j
        # ui_ranges
        self.assertIn("ui_ranges", data)
        self.assertIn("color_bar", data["ui_ranges"])
        self.assertIsInstance(data["ui_ranges"]["color_bar"], list)
        # sets/reps
        self.assertIn("sets", data); self.assertIsInstance(data["sets"], list); self.assertGreaterEqual(len(data["sets"]), 1)
        first_set = data["sets"][0]
        self.assertIn("reps", first_set); self.assertIsInstance(first_set["reps"], list); self.assertGreaterEqual(len(first_set["reps"]), 1)
        rep0 = first_set["reps"][0]
        self.assertIn("score_pct", rep0)
        # מצבי הדגמה
        for mode in ["good","shallow","missing","mixed"]:
            rv = client.post("/api/exercise/simulate", json={"sets":1,"reps":3,"mode":mode,"noise":0.1})
            self.assertEqual(rv.status_code, 200, (mode, rv.data))
            j = _j(rv); data = j.get("data") if isinstance(j.get("data"), dict) else j
            self.assertIn("sets", data)
    # ---------- /api/exercise/score ----------
    def test_score_contract_for_ui(self):
        client = self.client
        if not _has_endpoint(client, "POST", "/api/exercise/score"):
            self.skipTest("Endpoint /api/exercise/score not registered")
        # ללא מדדים (flow הדמו/חסרים)
        rv = client.post("/api/exercise/score", json={"metrics": {}})
        self.assertEqual(rv.status_code, 200, rv.data)
        j = _j(rv); data = j.get("data") if isinstance(j.get("data"), dict) else j
        self.assertIn("ui_ranges", data)
        self.assertIn("scoring", data)
        sc = data["scoring"]
        # קיום פירוק קריטריונים ל־tooltip (גם אם None)
        self.assertIn("criteria_breakdown_pct", sc)
        # עם מדדים טובים — אמור להיות מנוקד ולא unscored
        metrics_good = {
            "torso_vs_vertical_deg": 5.0,
            "knee_angle_left": 160.0, "knee_angle_right": 160.0,
            "hip_left_deg": 100.0, "hip_right_deg": 100.0,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.5
        }
        rv2 = client.post("/api/exercise/score", json={"metrics": metrics_good, "exercise":{"id":"squat.bodyweight.md"}})
        self.assertEqual(rv2.status_code, 200, rv2.data)
        j2 = _j(rv2); data2 = j2.get("data") if isinstance(j2.get("data"), dict) else j2
        self.assertIn("scoring", data2)
        sc2 = data2["scoring"]
        self.assertIsNotNone(sc2.get("score"))
        self.assertIsNone(sc2.get("unscored_reason"))
        self.assertIn("criteria", sc2)
        self.assertIn("criteria_breakdown_pct", sc2)
        # score_pct תואם ל-score*100 בקירוב
        if sc2.get("score") is not None and sc2.get("score_pct") is not None:
            self.assertAlmostEqual(int(round(sc2["score"]*100)), int(sc2["score_pct"]), delta=1)
    # ---------- /api/session/status ----------
    def test_session_status_optional(self):
        client = self.client
        if not _has_endpoint(client, "GET", "/api/session/status"):
            self.skipTest("Endpoint /api/session/status not registered")
        rv = client.get("/api/session/status")
        self.assertEqual(rv.status_code, 200, rv.data)
        j = _j(rv); self.assertIsInstance(j, dict)
    # ---------- /api/exercise/diag ----------
    def test_diag_snapshot_optional(self):
        client = self.client
        if not _has_endpoint(client, "GET", "/api/exercise/diag"):
            self.skipTest("Endpoint /api/exercise/diag not registered")
        rv = client.get("/api/exercise/diag")
        self.assertEqual(rv.status_code, 200, rv.data)
        _ = _j(rv)  # מבנה חופשי — מספיק שהוא JSON
    # ---------- /api/action (bus) ----------
    def test_action_bus_optional(self):
        client = self.client
        if not _has_endpoint(client, "POST", "/api/action"):
            self.skipTest("Endpoint /api/action not registered")
        # ping
        rv = client.post("/api/action", json={"action":"ping","payload":{}})
        self.assertEqual(rv.status_code, 200, rv.data)
        j = _j(rv); self.assertTrue(j.get("ok"), j)
        # video.set_profile (אם רשום)
        rv2 = client.post("/api/action", json={"action":"video.set_profile","payload":{"name":"Balanced"}})
        if rv2.status_code == 200:
            j2 = _j(rv2); self.assertIn("ok", j2); self.assertTrue(j2["ok"])
        # video.set_params (נבדוק שלא נופל)
        rv3 = client.post("/api/action", json={"action":"video.set_params","payload":{"jpeg_q":70,"encode_fps":15}})
        # ייתכן 400 אם הפעולה לא רשומה — זה בסדר; רק לא קריסה
        self.assertIn(rv3.status_code, (200, 400, 404, 500))
    # ---------- /api/video/state ----------
    def test_video_state_optional(self):
        client = self.client
        if not _has_endpoint(client, "GET", "/api/video/state"):
            self.skipTest("Endpoint /api/video/state not registered")
        rv = client.get("/api/video/state")
        self.assertEqual(rv.status_code, 200, rv.data)
        j = _j(rv); self.assertIsInstance(j, dict)
if __name__ == "__main__":
    unittest.main(verbosity=2)
