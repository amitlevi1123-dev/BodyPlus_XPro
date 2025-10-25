# -*- coding: utf-8 -*-

"""
Offline unit tests for admin_web.exercise_analyzer
==================================================
בדיקות אוף־ליין מקיפות ל:
- simulate_exercise
- analyze_exercise
- sanitize_metrics_payload

הקובץ עומד לריצה כ־Single Module:
    python -m unittest -v test_exercise_analyzer_offline
"""

import os
import sys
import json
import math
import unittest
from typing import Any, Dict, List

# ---------- Make sure project root is on sys.path ----------
# כך שלא משנה מאיפה מריצים – המודול יימצא
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------- Import SUT (System Under Test) ----------
try:
    from admin_web.exercise_analyzer import (
        analyze_exercise,
        simulate_exercise,
        sanitize_metrics_payload,
    )
except Exception as e:
    raise RuntimeError(
        "Import failed: cannot import from admin_web.exercise_analyzer. "
        "Make sure 'admin_web' is a package and exercise_analyzer.py exists."
    ) from e


# ---------- Helpers ----------
def _print_section(title: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n🧪 {title}\n{line}")

def _write_report(obj: Any, path: str) -> None:
    """כותב JSON לדוח תחת ./test_reports/"""
    try:
        base = os.path.join(_PROJECT_ROOT, "test_reports")
        os.makedirs(base, exist_ok=True)
        full = os.path.join(base, path)
        with open(full, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print(f"[saved] {full}")
    except Exception as e:
        print(f"[warn] failed writing report {path}: {e}")

def _expect_keys(d: Dict[str, Any], keys: List[str], ctx: str = "") -> None:
    missing = [k for k in keys if k not in d]
    if missing:
        raise AssertionError(f"Missing keys in {ctx}: {missing}")


class TestExerciseAnalyzerOffline(unittest.TestCase):
    """סט בדיקות אוף־ליין – לא תלוי ברשת/מצלמה/תלויות חיצוניות."""

    # ---------- sanitize_metrics_payload ----------

    def test_10_sanitize_basic(self):
        _print_section("sanitize_metrics_payload — קלט מעורב")
        raw = {
            "hip_left_deg": "120",
            "hip_right_deg": 125.5,
            "torso_vs_vertical_deg": "15.3",
            "rep.phase": "eccentric",
            "bool_true": "true",
            "bool_false": "false",
            "garbage": "abc",
            "nan_like": "NaN",
            "none": None,
        }
        clean = sanitize_metrics_payload(raw)
        print("in :", raw)
        print("out:", clean)
        _write_report({"sanitized": clean}, "01_sanitize_basic.json")

        self.assertIn("hip_left_deg", clean)
        self.assertIsInstance(clean["hip_left_deg"], float)
        self.assertNotIn("garbage", clean)
        # מחרוזות מורשות
        self.assertIn("rep.phase", clean)
        self.assertEqual(clean["rep.phase"], "eccentric")
        # בוליאנים
        self.assertIn("bool_true", clean)
        self.assertIs(clean["bool_true"], True)
        self.assertIs(clean["bool_false"], False)

    def test_11_sanitize_filters_non_finite(self):
        _print_section("sanitize_metrics_payload — סינון ערכים לא סופיים")
        raw = {"a": float("inf"), "b": "-inf", "c": "nan", "d": 123}
        clean = sanitize_metrics_payload(raw)
        print("in :", raw)
        print("out:", clean)
        _write_report({"sanitized": clean}, "02_sanitize_non_finite.json")
        self.assertEqual(clean, {"d": 123.0})

    # ---------- simulate_exercise ----------

    def test_20_simulate_structure(self):
        _print_section("simulate_exercise — מבנה")
        sim = simulate_exercise(sets=2, reps=5, mean_score=0.8, std=0.05)
        print(json.dumps(sim, ensure_ascii=False, indent=2))
        _write_report(sim, "10_simulate_structure.json")

        self.assertIn("ok", sim)
        self.assertTrue(sim["ok"])
        self.assertIn("sets", sim)
        self.assertGreaterEqual(len(sim["sets"]), 1)

        s0 = sim["sets"][0]
        _expect_keys(s0, ["set", "reps"], "sets[0]")
        self.assertGreaterEqual(len(s0["reps"]), 1)

        r0 = s0["reps"][0]
        _expect_keys(r0, ["rep", "score", "score_pct"], "reps[0]")
        self.assertTrue(0.0 <= float(r0["score"]) <= 1.0)
        self.assertTrue(0 <= int(r0["score_pct"]) <= 100)

    def test_21_simulate_bounds(self):
        _print_section("simulate_exercise — קלמפים")
        sim = simulate_exercise(sets=999, reps=999, mean_score=-1, std=9)
        print(json.dumps(sim, ensure_ascii=False, indent=2))
        _write_report(sim, "11_simulate_bounds.json")
        # אמור לקלמפ: sets<=10, reps<=30, mean∈[0..1], std∈[0..0.5]
        self.assertLessEqual(sim.get("sets_total", 0), 10)
        self.assertLessEqual(sim.get("reps_total", 0), 30)

    def test_22_simulate_deterministic(self):
        _print_section("simulate_exercise — דטרמיניזם")
        a = simulate_exercise(reps=4, mean_score=0.7, std=0.1)
        b = simulate_exercise(reps=4, mean_score=0.7, std=0.1)
        _write_report({"A": a, "B": b}, "12_simulate_deterministic.json")
        self.assertEqual(a, b, "simulate_exercise צריך להיות דטרמיניסטי (seed קבוע)")

    # ---------- analyze_exercise ----------

    def test_30_analyze_with_good_metrics(self):
        _print_section("analyze_exercise — מדדים טובים")
        payload = {
            "metrics": {
                "knee_angle_left": 130,
                "knee_angle_right": 135,
                "hip_left_deg": 100,
                "hip_right_deg": 102,
                "torso_vs_vertical_deg": 10,
                "feet_w_over_shoulders_w": 1.2,
                "rep_time_s": 1.5,
            }
        }
        res = analyze_exercise(payload)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        _write_report(res, "20_analyze_good.json")

        self.assertIn("scoring", res)
        sc = res["scoring"]
        _expect_keys(sc, ["score", "score_pct", "grade", "criteria"], "scoring")
        if sc.get("score") is not None:
            self.assertTrue(0.0 <= float(sc["score"]) <= 1.0)
        if sc.get("score_pct") is not None:
            self.assertTrue(0 <= int(sc["score_pct"]) <= 100)

    def test_31_analyze_missing_metrics(self):
        _print_section("analyze_exercise — ללא מדדים (unscored/demo)")
        res = analyze_exercise({})
        print(json.dumps(res, ensure_ascii=False, indent=2))
        _write_report(res, "21_analyze_missing.json")

        self.assertIn("scoring", res)
        sc = res["scoring"]
        # לא נכשל אם מחזיר דמו עם ציון, אבל מחייב unscored_reason או קריטריונים חסרים
        self.assertTrue(
            ("unscored_reason" in sc) or (isinstance(sc.get("criteria"), list) and sc["criteria"]),
            "expected unscored_reason or criteria list when no metrics provided",
        )

    def test_32_analyze_extremes(self):
        _print_section("analyze_exercise — ערכים קיצוניים")
        payload = {
            "metrics": {
                "knee_angle_left": 999,
                "knee_angle_right": -999,
                "hip_left_deg": 0,
                "hip_right_deg": 300,
                "torso_vs_vertical_deg": 180,
                "feet_w_over_shoulders_w": 10,
                "rep_time_s": 0.05,
            }
        }
        res = analyze_exercise(payload)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        _write_report(res, "22_analyze_extremes.json")

        self.assertIn("scoring", res)
        self.assertIn("criteria", res["scoring"])
        # לא לקרוס גם אם ניקוד נמוך/הערות
        self.assertIsInstance(res["scoring"]["criteria"], list)

    def test_33_analyze_aliases(self):
        _print_section("analyze_exercise — אליאסים שמות חלופיים")
        payload = {
            "metrics": {
                "knee_angle_left_deg": 132,
                "knee_angle_right_deg": 134,
                "hip_left_deg": 102,
                "hip_right_deg": 101,
                "torso_vs_vertical_deg": 12,
                "feet_w_over_shoulders_w": 1.25,
                "rep_time_s": 1.7,
            }
        }
        res = analyze_exercise(payload)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        _write_report(res, "23_analyze_aliases.json")

        self.assertIn("scoring", res)
        self.assertIsInstance(res["scoring"].get("criteria"), list)

    def test_34_analyze_no_mutation(self):
        _print_section("analyze_exercise — לא משנה את ה־payload")
        payload = {
            "metrics": {
                "knee_angle_left": 130,
                "knee_angle_right": 135,
            }
        }
        before = json.dumps(payload, sort_keys=True)
        _ = analyze_exercise(payload)
        after = json.dumps(payload, sort_keys=True)
        self.assertEqual(before, after, "analyze_exercise לא אמור לשנות את הקלט")

    def test_35_analyze_score_pct_consistency(self):
        _print_section("analyze_exercise — score_pct תואם score")
        payload = {
            "metrics": {
                "knee_angle_left": 130,
                "knee_angle_right": 135,
                "hip_left_deg": 100,
                "hip_right_deg": 102,
                "torso_vs_vertical_deg": 10,
                "feet_w_over_shoulders_w": 1.2,
                "rep_time_s": 1.5,
            }
        }
        res = analyze_exercise(payload)
        sc = res.get("scoring", {})
        score = sc.get("score")
        score_pct = sc.get("score_pct")
        print(f"score={score}  score_pct={score_pct}")
        if (score is not None) and (score_pct is not None):
            self.assertEqual(int(round(float(score) * 100)), int(score_pct))

    def test_36_overall_health_indicator(self):
        _print_section("בריאות כוללת — אינדיקציות מהירות")
        sim = simulate_exercise()
        res = analyze_exercise(sim)
        clean = sanitize_metrics_payload({"a": "5.5", "b": "x"})
        indicators = {
            "simulate_has_sets": bool(sim.get("sets")),
            "analyze_has_scoring": isinstance(res.get("scoring"), dict),
            "sanitize_numeric_only_ok": ("a" in clean and "b" not in clean),
        }
        print("indicators:", indicators)
        _write_report(
            {"simulate": sim, "analyze": res, "sanitize": clean, "indicators": indicators},
            "29_overall_health.json",
        )
        self.assertTrue(all(indicators.values()), f"health check failed: {indicators}")


# ---- Direct run (works in PyCharm Run, too) ----
if __name__ == "__main__":
    unittest.main(verbosity=2)
