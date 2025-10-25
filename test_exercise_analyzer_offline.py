# -*- coding: utf-8 -*-
"""
Offline tests for admin_web.exercise_analyzer

הקובץ עומד לרוץ בשורש הפרויקט:
> python -m unittest test_exercise_analyzer_offline -v

הטסטים:
- sanitize_metrics_payload: בדיקות סניטציה קלאסיות
- simulate_exercise: סכימה, דטרמיניזם, טווחים
- analyze_exercise: תרחישי good/partial/bad/aliases/no-metrics
- דוח מסכם ל-json בתיקייה test_reports
"""

from __future__ import annotations
import os, sys, json, math, pathlib, unittest
from typing import Any, Dict, List

# --- וודא ששורש הפרויקט ב-PYTHONPATH גם אם מריצים מדיר אחר ---
PROJECT_ROOT = pathlib.Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# --- ייבוא מודול הנבדק ---
try:
    from admin_web.exercise_analyzer import (
        sanitize_metrics_payload,
        simulate_exercise,
        analyze_exercise,
    )
except Exception as e:
    raise SystemExit(f"Cannot import admin_web.exercise_analyzer: {e}")


def _score_pct_of(report: Dict[str, Any]) -> int | None:
    s = report.get("scoring", {})
    v = s.get("score_pct")
    if v is None:
        sc = s.get("score")
        return None if sc is None else int(round(float(sc) * 100))
    return int(v)


def _safe_get(d: Dict[str, Any], path: str, default=None):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


class TestSanitizeMetrics(unittest.TestCase):
    def test_sanitize_basic_numbers_and_strings(self):
        raw = {
            "a": 1,
            "b": 2.5,
            "c": "3",
            "d": "4.75",
            "e": " true ",
            "f": "False",
            "rep.phase": "down",
            "view.mode": "pose",
            "junk": "abc",
        }
        out = sanitize_metrics_payload(raw)
        self.assertEqual(out["a"], 1.0)
        self.assertEqual(out["b"], 2.5)
        self.assertEqual(out["c"], 3.0)
        self.assertEqual(out["d"], 4.75)
        self.assertIs(out["e"], True)
        self.assertIs(out["f"], False)
        self.assertEqual(out["rep.phase"], "down")
        self.assertEqual(out["view.mode"], "pose")
        self.assertNotIn("junk", out)

    def test_sanitize_filters_non_finite(self):
        raw = {"x": float("nan"), "y": float("inf"), "z": "-inf"}
        out = sanitize_metrics_payload(raw)
        # אמורים להיזרק ולא להופיע
        self.assertNotIn("x", out)
        self.assertNotIn("y", out)
        self.assertNotIn("z", out)

    def test_sanitize_booleans_and_integers(self):
        raw = {"flag": True, "n": 7}
        out = sanitize_metrics_payload(raw)
        self.assertIs(out["flag"], True)
        self.assertEqual(out["n"], 7.0)


class TestSimulateExercise(unittest.TestCase):
    def test_simulate_defaults_schema(self):
        sim = simulate_exercise()
        self.assertIsInstance(sim, dict)
        self.assertIn("sets", sim)
        self.assertIsInstance(sim["sets"], list)
        self.assertGreaterEqual(len(sim["sets"]), 1)
        s0 = sim["sets"][0]
        self.assertIn("reps", s0)
        self.assertIsInstance(s0["reps"], list)
        self.assertGreaterEqual(len(s0["reps"]), 1)
        r0 = s0["reps"][0]
        for k in ("rep", "score", "score_pct"):
            self.assertIn(k, r0)
        self.assertTrue(0 <= r0["score"] <= 1)
        self.assertTrue(0 <= r0["score_pct"] <= 100)

    def test_simulate_is_deterministic(self):
        a = simulate_exercise(sets=1, reps=5, mean_score=0.73, std=0.12)
        b = simulate_exercise(sets=1, reps=5, mean_score=0.73, std=0.12)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_simulate_bounds_and_clamping(self):
        sim = simulate_exercise(sets=99, reps=999, mean_score=2.0, std=1.0)
        # מגבלות: sets<=10, reps<=30, 0<=score<=1
        self.assertLessEqual(sim.get("sets_total", 10), 10)
        self.assertLessEqual(sim.get("reps_total", 30), 30)
        for s in sim.get("sets", []):
            for r in s.get("reps", []):
                self.assertTrue(0.0 <= float(r["score"]) <= 1.0)


class TestAnalyzeExercise(unittest.TestCase):
    def test_analyze_with_good_metrics_returns_scored(self):
        payload = {"exercise": {"id": "squat.bodyweight"}, "metrics": {
            "knee_angle_left": 125.0, "knee_angle_right": 126.0,
            "hip_left_deg": 95.0, "hip_right_deg": 98.0,
            "torso_vs_vertical_deg": 8.0,
            "feet_w_over_shoulders_w": 1.22,
            "rep_time_s": 1.6,
        }}
        rep = analyze_exercise(payload)
        pct = _score_pct_of(rep)
        self.assertIsNotNone(pct)
        self.assertGreaterEqual(pct, 70)
        self.assertIsNone(_safe_get(rep, "scoring.unscored_reason"))

    def test_analyze_with_bad_depth_and_valgus(self):
        payload = {"metrics": {
            "knee_angle_left": 165.0, "knee_angle_right": 145.0,  # אסימטריה + עומק רדוד
            "hip_left_deg": 130.0, "hip_right_deg": 130.0,
            "torso_vs_vertical_deg": 28.0,
            "feet_w_over_shoulders_w": 1.6,
            "rep_time_s": 0.6,
        }}
        rep = analyze_exercise(payload)
        pct = _score_pct_of(rep)
        # יכול להיות ציון נמוך או unscored אם הכל גרוע
        if pct is not None:
            self.assertLess(pct, 70)
        hints = rep.get("hints", [])
        self.assertIsInstance(hints, list)

    def test_analyze_handles_partial_metrics(self):
        payload = {"metrics": {
            "knee_angle_left": 140.0,  # חסרים כמה מדדים אבל חלק קיים
            "knee_angle_right": 141.0,
            # no hip*, no stance
            "torso_vs_vertical_deg": 15.0,
            "rep_time_s": 2.2,
        }}
        rep = analyze_exercise(payload)
        # לא אמור לקרוס; או ציון חלקי או unscored
        _ = rep.get("scoring", {})
        self.assertIn("criteria", _)

    def test_analyze_with_aliases_are_respected(self):
        payload = {"metrics": {
            "knee_angle_left_deg": 128.0,
            "knee_angle_right_deg": 129.0,
            "torso_vs_vertical_deg": 9.0,
            "hip_left_deg": 101.0,
            "hip_right_deg": 102.0,
            "feet_w_over_shoulders_w": 1.21,
            "rep_time_s": 1.4,
        }}
        rep = analyze_exercise(payload)
        pct = _score_pct_of(rep)
        self.assertIsNotNone(pct)
        self.assertGreaterEqual(pct, 65)

    def test_analyze_no_metrics_tolerant(self):
        """
        תרחיש ללא מדדים:
        - ייתכן שהמנתח יחזיר ענף 'unscored' עם score=None ו-unscored_reason
        - או ענף DEMO (כמו בקוד הישן) עם score>0 אך עדיין unscored_reason מוגדר.
        שני המצבים נחשבים תקינים עבור הטסט.
        """
        rep = analyze_exercise({})
        scoring = rep.get("scoring", {})
        score = scoring.get("score")
        unscored_reason = scoring.get("unscored_reason")
        # אחד משני המצבים:
        ok_unscored = (score is None and unscored_reason is not None)
        ok_demo = (isinstance(score, (int, float)) and unscored_reason is not None)
        self.assertTrue(ok_unscored or ok_demo,
                        f"Unexpected behavior for no-metrics: score={score!r}, unscored_reason={unscored_reason!r}")

    def test_analyze_score_pct_matches_score(self):
        payload = {"metrics": {
            "knee_angle_left": 130.0, "knee_angle_right": 130.0,
            "hip_left_deg": 100.0, "hip_right_deg": 100.0,
            "torso_vs_vertical_deg": 5.0,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.7,
        }}
        rep = analyze_exercise(payload)
        s = rep.get("scoring", {})
        sc = s.get("score")
        pct = s.get("score_pct")
        if sc is not None:
            self.assertIsInstance(sc, float)
            self.assertEqual(int(round(float(sc) * 100)), int(pct or 0))


# --------------------------
# דוח מסכם אחרי הרצת הטסטים
# --------------------------
def _write_summary_json(result: unittest.TestResult) -> str:
    out_dir = PROJECT_ROOT / "test_reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "summary.json"

    summary = {
        "total": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(getattr(result, "skipped", [])),
        "details": {
            "failures": [{"test": str(t), "trace": tr} for (t, tr) in result.failures],
            "errors": [{"test": str(t), "trace": tr} for (t, tr) in result.errors],
        },
    }
    status = "OK" if (not result.failures and not result.errors) else "NOT_OK"
    summary["final_status"] = status

    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return str(path)


def load_tests(loader, tests, pattern):
    """
    מאפשר הרצה גם כמודול יחיד וגם כ-discover.
    לא נדרש שינוי, רק משפר תאימות.
    """
    return tests


if __name__ == "__main__":
    # מריץ את ה-unittest ומדפיס סיכום ברור
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    res = runner.run(suite)

    report_path = _write_summary_json(res)
    print("\n" + "=" * 70)
    print(f" Summary JSON written to: {report_path}")
    print(f" Final Status: {'OK ✅' if (not res.failures and not res.errors) else 'NOT OK ❌'}")
    print("=" * 70)
