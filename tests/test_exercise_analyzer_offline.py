# -*- coding: utf-8 -*-
"""
בדיקה אוף-ליין למנוע הניתוח והציונים של BodyPlus_XPro
------------------------------------------------------
מטרות:
1. לוודא שכל הפונקציות המרכזיות זמינות ועובדות (simulate_exercise, analyze_exercise, sanitize_metrics_payload)
2. לוודא שאין חריגות, ערכים שגויים או קריסות
3. לייצר דוח מצב סופי בתיקייה /test_reports עם סטטוס כללי (OK / FAIL)
הרצה:
    python -m unittest -v test_exercise_analyzer_offline
"""

import os, sys, json, unittest
from typing import Any, Dict

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ייבוא המודול הראשי לבדיקה
try:
    from admin_web.exercise_analyzer import (
        analyze_exercise,
        simulate_exercise,
        sanitize_metrics_payload
    )
except Exception as e:
    raise SystemExit(f"❌ לא ניתן לייבא את exercise_analyzer: {e}")

REPORT_DIR = os.path.join(ROOT, "test_reports")
os.makedirs(REPORT_DIR, exist_ok=True)

def save_report(name: str, data: Dict[str, Any]):
    """כותב דוח JSON קטן (מצב כללי בלבד)"""
    path = os.path.join(REPORT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

class TestExerciseAnalyzerOffline(unittest.TestCase):
    """בדיקות שקטות וממוקדות"""

    def test_imports_exist(self):
        """בודק שכל הפונקציות קיימות"""
        self.assertTrue(callable(simulate_exercise))
        self.assertTrue(callable(analyze_exercise))
        self.assertTrue(callable(sanitize_metrics_payload))

    def test_simulation_returns_structure(self):
        """בודק ש-simulate_exercise מחזיר מבנה תקין"""
        sim = simulate_exercise()
        self.assertIn("ok", sim)
        self.assertTrue(sim["ok"])
        self.assertIn("sets", sim)
        self.assertGreater(len(sim["sets"]), 0)
        rep = sim["sets"][0]["reps"][0]
        self.assertIn("score", rep)
        self.assertTrue(0.0 <= rep["score"] <= 1.0)

    def test_analyze_with_valid_metrics(self):
        """בודק ש-analyze_exercise מחשב ציונים עם מדדים תקינים"""
        payload = {"metrics": {
            "knee_angle_left": 130,
            "knee_angle_right": 135,
            "hip_left_deg": 100,
            "hip_right_deg": 102,
            "torso_vs_vertical_deg": 10,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.5
        }}
        res = analyze_exercise(payload)
        self.assertIn("scoring", res)
        sc = res["scoring"]
        self.assertIn("score", sc)
        self.assertTrue(0.0 <= sc["score"] <= 1.0)

    def test_analyze_handles_missing(self):
        """בודק ש-analyze_exercise לא קורס כשאין מדדים"""
        res = analyze_exercise({})
        self.assertIn("scoring", res)
        self.assertIsInstance(res["scoring"], dict)

    def test_sanitize_removes_invalid(self):
        """בודק ש-sanitize_metrics_payload מנקה ערכים לא תקינים"""
        raw = {"hip_left_deg": "120", "bad": "abc", "none": None}
        clean = sanitize_metrics_payload(raw)
        self.assertIn("hip_left_deg", clean)
        self.assertNotIn("bad", clean)
        self.assertNotIn("none", clean)

    def test_end_to_end_flow(self):
        """בדיקה כוללת — סימולציה > ניתוח > דוח מצב"""
        sim = simulate_exercise()
        res = analyze_exercise(sim)
        clean = sanitize_metrics_payload({"a": "5.5", "b": "x"})
        ok = (
            sim.get("ok") is True and
            isinstance(res.get("scoring"), dict) and
            "a" in clean and "b" not in clean
        )
        save_report("summary.json", {
            "simulate_ok": sim.get("ok"),
            "analyze_scoring_exists": "scoring" in res,
            "sanitize_worked": ok,
            "final_status": "OK" if ok else "FAIL"
        })
        self.assertTrue(ok, "בדיקה כוללת נכשלה")

if __name__ == "__main__":
    unittest.main(verbosity=1)
