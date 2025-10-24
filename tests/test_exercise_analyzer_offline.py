# -*- coding: utf-8 -*-
"""
tests/test_exercise_analyzer_offline.py
=======================================

בדיקות אוף־ליין מפורטות למודול:
    admin_web/exercise_analyzer.py

מטרות:
- לוודא שהסכמות של הפלטים יציבות (שדות/טיפוסים/טווחים).
- לאשש לוגיקה של קריטריונים, ממוצעים, ו-ranges ל-UI.
- לבדוק סניטציה מול קלטים "מלוכלכים".
- לבדוק סימולציה במצבי good/shallow/missing/mixed + noise.
- לבדוק אנליזה עם payloadים מלאים/חלקיים/שגויים.
- לאסוף דו״ח קריא ומפורט על כל חריגה – כולל ציון מיקום/שורה.

אפשר להריץ:
    python -m unittest -v tests/test_exercise_analyzer_offline.py
או:
    python tests/test_exercise_analyzer_offline.py -v
"""

from __future__ import annotations
import os
import sys
import time
import json
import math
import random
import traceback
import unittest
from typing import Any, Dict, List, Optional, Tuple

# ---- נתיב ייבוא למודול הנבדק ----
# במידה ואתה מריץ ממבנה פרויקט, ודא שה-root בפייתון־פאת':
# לדוגמה, אם הקובץ הזה נמצא תחת ./tests, נרים את ה-root:
HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- המודול הנבדק ----
try:
    from admin_web.exercise_analyzer import (
        sanitize_metrics_payload,
        simulate_exercise,
        analyze_exercise,
    )
except Exception as e:
    print("FATAL: failed importing admin_web.exercise_analyzer:", e)
    raise


# ======================================================================================
#                                Utilities for tests
# ======================================================================================

def _assert_between(testcase: unittest.TestCase, v: float, lo: float, hi: float, msg: str = "") -> None:
    """מאשש שערך נמצא בטווח [lo..hi]."""
    testcase.assertIsNotNone(v, msg or "value is None")
    testcase.assertTrue(isinstance(v, (int, float)), msg or f"value not numeric: {type(v)}")
    testcase.assertTrue(math.isfinite(float(v)), msg or f"value not finite: {v!r}")
    testcase.assertGreaterEqual(float(v), lo, msg or f"value {v} < {lo}")
    testcase.assertLessEqual(float(v), hi, msg or f"value {v} > {hi}")

def _assert_pct(testcase: unittest.TestCase, v: Optional[int], msg: str = "") -> None:
    if v is None:
        return
    testcase.assertTrue(isinstance(v, int), msg or f"pct not int: {v!r}")
    testcase.assertGreaterEqual(v, 0, msg or f"{v} < 0")
    testcase.assertLessEqual(v, 100, msg or f"{v} > 100")

def _assert_in(testcase: unittest.TestCase, v: Any, seq: List[Any], msg: str = "") -> None:
    testcase.assertIn(v, seq, msg or f"value {v!r} not in {seq!r}")

def _safe(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return repr(obj)

def _now_ms() -> int:
    return int(time.time() * 1000)


# ======================================================================================
#                                     Test Report
# ======================================================================================

class RichResult(unittest.TextTestResult):
    """
    תוצאת בדיקות עם הדפסות עשירות, זמן ריצה, ופרטים עד לרמת חריגה.
    ללא תלות בחבילות צד ג'.
    """
    def startTest(self, test):
        self._start = time.perf_counter()
        super().startTest(test)

    def addSuccess(self, test):
        dur = (time.perf_counter() - getattr(self, "_start", time.perf_counter())) * 1000.0
        sys.stdout.write(f"✔ PASS  {test.id()}  [{dur:.2f} ms]\n")
        super().addSuccess(test)

    def addFailure(self, test, err):
        dur = (time.perf_counter() - getattr(self, "_start", time.perf_counter())) * 1000.0
        sys.stdout.write(f"✘ FAIL  {test.id()}  [{dur:.2f} ms]\n")
        tb_text = "".join(traceback.format_exception(*err))
        sys.stdout.write("---- Failure details ----\n")
        sys.stdout.write(tb_text + "\n")
        super().addFailure(test, err)

    def addError(self, test, err):
        dur = (time.perf_counter() - getattr(self, "_start", time.perf_counter())) * 1000.0
        sys.stdout.write(f"‼ ERROR {test.id()}  [{dur:.2f} ms]\n")
        tb_text = "".join(traceback.format_exception(*err))
        sys.stdout.write("---- Error details ----\n")
        sys.stdout.write(tb_text + "\n")
        super().addError(test, err)


class RichRunner(unittest.TextTestRunner):
    resultclass = RichResult


# ======================================================================================
#                              Golden / Sample payload builders
# ======================================================================================

def sample_metrics_full() -> Dict[str, Any]:
    """payload מלא עם metrics טובים (סקווט גוף)."""
    return {
        "exercise": {"id": "squat.bodyweight"},
        "metrics": {
            "torso_vs_vertical_deg": 8.0,  # טוב
            "knee_angle_left": 140.0,
            "knee_angle_right": 141.0,
            "hip_left_deg": 95.0,
            "hip_right_deg": 100.0,
            "feet_w_over_shoulders_w": 1.22,
            "rep_time_s": 1.4,
        }
    }

def sample_metrics_partial_missing_knees() -> Dict[str, Any]:
    """payload חלקי – חסרות זוויות ברכיים, יש ירך/גב/קצב/רוחב."""
    return {
        "exercise": {"id": "squat.bodyweight"},
        "metrics": {
            "torso_vs_vertical_deg": 15.0,
            "hip_left_deg": 98.0,
            "hip_right_deg": 101.0,
            "feet_w_over_shoulders_w": 1.1,
            "rep_time_s": 1.9,
        }
    }

def sample_metrics_bad_values() -> Dict[str, Any]:
    """payload עם מחרוזות/בוליאנים/זבל – כדי לבדוק sanitize."""
    return {
        "exercise": {"id": "squat.bodyweight"},
        "metrics": {
            "torso_vs_vertical_deg": "8.0",
            "knee_angle_left": "141",
            "knee_angle_right": "not_a_number",
            "hip_left_deg": True,   # צריך ליפול
            "hip_right_deg": " 100 ",
            "feet_w_over_shoulders_w": "1.22",
            "rep_time_s": "1.5",
            "rep.phase": "eccentric",
            "view.mode": "front",
            "view.primary": "camera1",
            "exercise.id": "squat.bodyweight",
        }
    }

def sample_metrics_empty() -> Dict[str, Any]:
    """payload ריק מבחינת metrics – אמור להיות 'unscored'."""
    return {
        "exercise": {"id": "squat.bodyweight"},
        "metrics": {
            "random_key": 123,
            "foo": "bar",
        }
    }

def golden_breakdown_keys() -> List[str]:
    """מפתחי קריטריונים הצפויים."""
    return ["depth", "knees", "torso_angle", "stance_width", "tempo"]


# ======================================================================================
#                                      Test Cases
# ======================================================================================

class TestSanitize(unittest.TestCase):
    """בדיקות סניטציה מקיפות."""

    def test_sanitize_numeric_and_strings(self):
        payload = sample_metrics_bad_values()
        clean = sanitize_metrics_payload(payload["metrics"])
        self.assertIsInstance(clean, dict)
        # should parse numeric strings, ignore boolean-as-floats
        self.assertAlmostEqual(clean.get("torso_vs_vertical_deg", -1), 8.0, places=5)
        self.assertAlmostEqual(clean.get("knee_angle_left", -1), 141.0, places=5)
        # right knee was "not_a_number" -> should be absent
        self.assertTrue("knee_angle_right" not in clean or isinstance(clean["knee_angle_right"], float) is False)
        # booleans should not be coerced to float (hip_left_deg=True) -> drop
        self.assertTrue("hip_left_deg" not in clean)
        # strings trimmed
        self.assertAlmostEqual(clean.get("hip_right_deg", -1), 100.0, places=5)
        self.assertAlmostEqual(clean.get("feet_w_over_shoulders_w", -1), 1.22, places=5)
        self.assertAlmostEqual(clean.get("rep_time_s", -1), 1.5, places=5)
        # allowed strings should pass through as strings
        self.assertEqual(clean.get("rep.phase"), "eccentric")
        self.assertEqual(clean.get("view.mode"), "front")
        self.assertEqual(clean.get("view.primary"), "camera1")
        self.assertEqual(clean.get("exercise.id"), "squat.bodyweight")

    def test_sanitize_non_dict(self):
        self.assertEqual(sanitize_metrics_payload(None), {})
        self.assertEqual(sanitize_metrics_payload(123), {})
        self.assertEqual(sanitize_metrics_payload("x"), {})

    def test_sanitize_edge_values(self):
        dirty = {
            "a": float("inf"),
            "b": float("-inf"),
            "c": float("nan"),
            "d": "   12   ",
            "e": "12.5",
            "f": "true",
            "g": "false",
            "h": True,
            "i": False,
        }
        clean = sanitize_metrics_payload(dirty)
        self.assertTrue("a" not in clean and "b" not in clean and "c" not in clean)
        self.assertEqual(clean.get("d"), 12.0)
        self.assertEqual(clean.get("e"), 12.5)
        self.assertTrue(isinstance(clean.get("f"), bool))
        self.assertTrue(isinstance(clean.get("g"), bool))
        self.assertTrue(isinstance(clean.get("h"), bool))
        self.assertTrue(isinstance(clean.get("i"), bool))


class TestSimulateExercise(unittest.TestCase):
    """בדיקות סימולציה – מבנה, טווחים, יציבות, מצבים, ורעש."""

    def _check_sim_schema(self, sim: Dict[str, Any], ctx: str = ""):
        self.assertTrue(sim.get("ok") in (True, False), f"{ctx}: ok missing/bad")
        self.assertIsInstance(sim.get("ui_ranges"), dict, f"{ctx}: ui_ranges missing")
        cb = sim["ui_ranges"].get("color_bar")
        self.assertIsInstance(cb, list, f"{ctx}: color_bar missing")
        self.assertGreaterEqual(len(cb), 1, f"{ctx}: color_bar empty")

        sets = sim.get("sets")
        self.assertIsInstance(sets, list, f"{ctx}: sets missing")
        for i, s in enumerate(sets, 1):
            self.assertIsInstance(s.get("set"), int, f"{ctx}: set index not int at i={i}")
            _assert_between(self, s.get("set_score"), 0.0, 1.0, f"{ctx}: set_score out of [0..1]")
            _assert_pct(self, s.get("set_score_pct"), f"{ctx}: set_score_pct")
            reps = s.get("reps")
            self.assertIsInstance(reps, list, f"{ctx}: reps missing")
            self.assertGreater(len(reps), 0, f"{ctx}: reps empty")
            for r in reps:
                self.assertIsInstance(r.get("rep"), int, f"{ctx}: rep idx")
                _assert_between(self, r.get("score"), 0.0, 1.0, f"{ctx}: rep score")
                _assert_pct(self, r.get("score_pct"), f"{ctx}: rep score_pct")
                self.assertIsInstance(r.get("notes"), list, f"{ctx}: rep notes")

    def test_sim_default(self):
        sim = simulate_exercise()
        self._check_sim_schema(sim, "default")
        # יציבות בסיסית: אותם פרמטרים אמורים לייצר אותם ערכים (seed=42)
        sim2 = simulate_exercise()
        self.assertEqual(json.dumps(sim, sort_keys=True), json.dumps(sim2, sort_keys=True))

    def test_sim_params_bounds(self):
        sim = simulate_exercise(sets=999, reps=999, mean_score=-1, std=999)
        self._check_sim_schema(sim, "bounds")
        self.assertEqual(sim.get("sets_total"), 10)  # clamp
        self.assertEqual(sim.get("reps_total"), 30)  # clamp
        # ודא שאף ציון לא יצא מהטווח – הפונקציה כבר בודקת בכל rep

    def test_sim_modes(self):
        for mode in ("good", "shallow", "missing", "mixed", "unknown"):
            sim = simulate_exercise(sets=2, reps=8, mode=mode, noise=0.12)
            self._check_sim_schema(sim, f"mode={mode}")
            # שונות בין מצבים (לא חייבת להיות גדולה, רק שלא הכל קבוע)
            # נוודא שיש לפחות שני ציונים שונים בסט אחד
            rep_scores = [r["score"] for r in sim["sets"][0]["reps"]]
            self.assertGreaterEqual(len(set(rep_scores)), 2, f"mode={mode}: scores too uniform")

    def test_sim_noise_effect(self):
        base = simulate_exercise(sets=1, reps=12, mode="good", noise=0.01)
        noisy = simulate_exercise(sets=1, reps=12, mode="good", noise=0.50)
        # טווח הפיזור צריך להיות גדול יותר כש-noise גדול
        def spread(sim):
            xs = [r["score"] for r in sim["sets"][0]["reps"]]
            return max(xs) - min(xs)
        self.assertLess(spread(base) + 1e-6, spread(noisy) + 1e-6)


class TestAnalyzeExercise(unittest.TestCase):
    """בדיקות אנליזה – מבנה דו״ח, קריטריונים, שדות UI, ו-unscored."""

    def _check_report_schema(self, rep: Dict[str, Any], ctx: str = ""):
        self.assertIsInstance(rep.get("exercise"), dict, f"{ctx}: exercise missing")
        self.assertTrue(isinstance(rep["exercise"].get("id"), str) and rep["exercise"]["id"], f"{ctx}: exercise.id")
        self.assertIsInstance(rep.get("ui_ranges"), dict, f"{ctx}: ui_ranges missing")
        cb = rep["ui_ranges"].get("color_bar")
        self.assertIsInstance(cb, list, f"{ctx}: color_bar missing")
        sc = rep.get("scoring")
        self.assertIsInstance(sc, dict, f"{ctx}: scoring missing")
        # שדות חובה ב-scoring
        self.assertTrue("score" in sc, f"{ctx}: scoring.score missing")
        self.assertTrue("score_pct" in sc, f"{ctx}: scoring.score_pct missing")
        self.assertTrue("grade" in sc, f"{ctx}: scoring.grade missing")
        self.assertTrue("quality" in sc, f"{ctx}: scoring.quality missing")
        self.assertTrue("unscored_reason" in sc, f"{ctx}: scoring.unscored_reason missing")
        self.assertTrue("criteria" in sc and isinstance(sc["criteria"], list), f"{ctx}: criteria list missing")
        self.assertTrue("criteria_breakdown_pct" in sc and isinstance(sc["criteria_breakdown_pct"], dict),
                        f"{ctx}: criteria_breakdown_pct missing")
        # טווחים
        if sc["score"] is not None:
            _assert_between(self, sc["score"], 0.0, 1.0, f"{ctx}: score out of range")
        _assert_pct(self, sc["score_pct"], f"{ctx}: score_pct")
        # grade/quality כצפוי (אחד מאותיות A..E או '—')
        self.assertTrue(isinstance(sc["grade"], str), f"{ctx}: grade type")
        self.assertTrue(isinstance(sc["quality"], str), f"{ctx}: quality type")
        # hints
        self.assertIsInstance(rep.get("hints"), list, f"{ctx}: hints type")
        # breakdown keys לפחות תת-קבוצה מהמצופה
        keys = list(rep["scoring"]["criteria_breakdown_pct"].keys())
        self.assertGreater(len(keys), 0, f"{ctx}: breakdown empty")

    def test_analyze_full(self):
        rep = analyze_exercise(sample_metrics_full())
        self._check_report_schema(rep, "full")
        # לבדוק שהקריטריונים כוללים את המפתח המרכזי 'depth'
        ids = [c.get("id") for c in rep["scoring"]["criteria"]]
        self.assertIn("depth", ids, "criteria missing 'depth'")
        # score_pct עקבי מול score
        sp = rep["scoring"]["score_pct"]
        sc = rep["scoring"]["score"]
        if sc is not None:
            self.assertEqual(sp, int(round(float(sc) * 100)))

    def test_analyze_partial(self):
        rep = analyze_exercise(sample_metrics_partial_missing_knees())
        self._check_report_schema(rep, "partial")
        # עדיין אמור להיות ניקוד (כי יש עומק משוער מירך/גב)
        self.assertIsNone(rep["scoring"]["unscored_reason"])
        self.assertIsNotNone(rep["scoring"]["score"])

    def test_analyze_empty_unscored(self):
        rep = analyze_exercise(sample_metrics_empty())
        self._check_report_schema(rep, "empty/unscored")
        # אמור להיות unscored
        self.assertEqual(rep["scoring"]["unscored_reason"], "missing_critical")
        self.assertIsNone(rep["scoring"]["score"])
        self.assertIsNone(rep["scoring"]["score_pct"])

    def test_breakdown_contains_expected_subset(self):
        rep = analyze_exercise(sample_metrics_full())
        breakdown = rep["scoring"]["criteria_breakdown_pct"]
        # וודא שהמפתחות קצרים/ידידותיים:
        for k in breakdown.keys():
            self.assertTrue(isinstance(k, str) and k, f"breakdown key bad: {k!r}")
        # תת-קבוצה:
        expected_subset = set(golden_breakdown_keys())
        self.assertTrue(len(set(breakdown.keys()) & expected_subset) >= 2, "breakdown missing key subset")

    def test_scores_in_range_and_monotonicity(self):
        # נבדוק ש-score_pct = round(score*100) (כאשר score!=None)
        for payload in (sample_metrics_full(), sample_metrics_partial_missing_knees()):
            rep = analyze_exercise(payload)
            sc = rep["scoring"]["score"]
            sp = rep["scoring"]["score_pct"]
            if sc is not None:
                self.assertEqual(sp, int(round(float(sc) * 100)))
                _assert_between(self, sc, 0.0, 1.0)
                _assert_pct(self, sp)

    def test_consistency_with_simulation(self):
        # סימולציה -> נרכיב payload מלאכותי מ-rep ראשון ונוודא שהאנלייזר לא מתפרק
        sim = simulate_exercise(sets=1, reps=5, mode="mixed", noise=0.2)
        rep_like = sim["sets"][0]["reps"][0]
        # נבנה payload סביר (האנליזה לא משתמשת ב-score החיצוני; היא תגזור מה-metrics):
        # כאן נשתול metrics סבירים:
        payload = {
            "exercise": {"id": "squat.bodyweight"},
            "metrics": {
                "torso_vs_vertical_deg": 10.0,
                "knee_angle_left": 145.0,
                "knee_angle_right": 142.0,
                "hip_left_deg": 95.0,
                "hip_right_deg": 105.0,
                "feet_w_over_shoulders_w": 1.25,
                "rep_time_s": 1.6,
            }
        }
        rep = analyze_exercise(payload)
        self._check_report_schema(rep, "consistency/sim→analyze")
        # הפלט חייב להכיל קריטריונים ו-breakdown
        self.assertGreater(len(rep["scoring"]["criteria"]), 0)

    def test_hints_reasonable(self):
        rep = analyze_exercise(sample_metrics_full())
        hints = rep.get("hints") or []
        self.assertTrue(isinstance(hints, list))
        # לא דורשים טקסטים ספציפיים, רק שלא יהיו >3 ושיהיו ייחודיים
        self.assertLessEqual(len(hints), 3)
        self.assertEqual(len(set(hints)), len(hints))


class TestFuzzAndEdgeCases(unittest.TestCase):
    """בדיקות Fuzz (עם seed) וקצה – מבטיחות יציבות ותיקוף שדות."""

    def setUp(self):
        self.rng = random.Random(1337)

    def _random_payload(self) -> Dict[str, Any]:
        """
        יוצר payload רנדומלי אך סביר. חלק מהערכים ייעדרו כדי לדמות חוסר מדדים.
        """
        def prob(p): return self.rng.random() < p
        def maybe(v, p=0.7): return v if prob(p) else None

        payload = {
            "exercise": {"id": "squat.bodyweight"},
            "metrics": {}
        }
        # חלק מהשדות יוכנסו כמחרוזות כדי לבדוק sanitize
        if prob(0.8): payload["metrics"]["torso_vs_vertical_deg"] = self.rng.choice([str(round(self.rng.uniform(0, 40), 2)), round(self.rng.uniform(0, 40), 2)])
        if prob(0.8): payload["metrics"]["knee_angle_left"] = self.rng.choice([round(self.rng.uniform(110, 175), 2), "notnum", "170"])
        if prob(0.8): payload["metrics"]["knee_angle_right"] = self.rng.choice([round(self.rng.uniform(110, 175), 2), "173.5"])
        if prob(0.8): payload["metrics"]["hip_left_deg"] = self.rng.choice([round(self.rng.uniform(60, 140), 2), True, False, "100"])
        if prob(0.8): payload["metrics"]["hip_right_deg"] = self.rng.choice([round(self.rng.uniform(60, 140), 2), " 99 "])
        if prob(0.8): payload["metrics"]["feet_w_over_shoulders_w"] = self.rng.choice([round(self.rng.uniform(0.5, 2.0), 3), "1.3"])
        if prob(0.8): payload["metrics"]["rep_time_s"] = self.rng.choice([round(self.rng.uniform(0.4, 3.5), 3), "1.8"])
        # allowed strings
        if prob(0.5): payload["metrics"]["rep.phase"] = self.rng.choice(["eccentric", "concentric"])
        if prob(0.5): payload["metrics"]["view.mode"] = self.rng.choice(["front", "side"])
        if prob(0.5): payload["metrics"]["view.primary"] = "camera1"
        if prob(0.5): payload["metrics"]["exercise.id"] = "squat.bodyweight"
        return payload

    def test_fuzz_many_random_payloads(self):
        N = 120
        unscored = 0
        for i in range(N):
            payload = self._random_payload()
            rep = analyze_exercise(payload)
            # סכימה בסיסית
            self.assertTrue(isinstance(rep.get("ui_ranges"), dict))
            sc = rep.get("scoring") or {}
            self.assertTrue("criteria" in sc and isinstance(sc["criteria"], list))
            # מגבלות
            if sc.get("score") is not None:
                _assert_between(self, sc["score"], 0.0, 1.0)
            _assert_pct(self, sc.get("score_pct"))
            if sc.get("unscored_reason"):
                unscored += 1
        # נרצה שרוב הרנדומים יהיו ניתנים לניקוד חלקי (לא כולם unscored),
        # אבל עדיין שתהיה אוכלוסיה מסוימת של unscored. נבדוק יחס מאוזן:
        self.assertLess(unscored, N * 0.7, f"too many unscored: {unscored}/{N}")

    def test_extreme_inputs_no_crash(self):
        # וודא שגם עם "זבל" קיצוני לא קורסים:
        dirty_list = [
            None, 123, "xxx", [], set(),
            {"exercise": {"id": ""}, "metrics": {"knee_angle_left": float("inf")}},
            {"exercise": {"id": "x"}, "metrics": {"knee_angle_left": float("nan")}},
            {"exercise": {"id": "x"}, "metrics": {"rep_time_s": "-999999999999999999999999"}},
        ]
        for obj in dirty_list:
            rep = analyze_exercise(obj if isinstance(obj, dict) else {"exercise": {"id": "x"}, "metrics": obj})
            # רק דורשים מבנה יציב וחוסר קריסה
            self.assertTrue(isinstance(rep, dict))
            self.assertTrue(isinstance(rep.get("scoring"), dict))
            self.assertTrue(isinstance(rep.get("ui_ranges"), dict))


class TestGoldenScenarios(unittest.TestCase):
    """בדיקות Golden – השוואה לתוצאות ידועות פחות או יותר (טולרנטיות)."""

    def test_golden_full_quality_high(self):
        rep = analyze_exercise(sample_metrics_full())
        sc = rep["scoring"]
        # מצפים לציון לא נמוך מאוד (מעל 0.6), לא מחייבים ערך מדויק
        if sc["score"] is not None:
            self.assertGreaterEqual(sc["score"], 0.6)
            self.assertIsNone(sc["unscored_reason"])
            # breakdown חייב להכיל את depth
            self.assertIn("depth", sc["criteria_breakdown_pct"].keys())

    def test_golden_partial_has_score(self):
        rep = analyze_exercise(sample_metrics_partial_missing_knees())
        sc = rep["scoring"]
        # יש עומק מהירכיים, אז לא אמור להיות missing_critical
        self.assertIsNone(sc["unscored_reason"])
        self.assertIsNotNone(sc["score"])

    def test_golden_empty_is_unscored(self):
        rep = analyze_exercise(sample_metrics_empty())
        sc = rep["scoring"]
        self.assertEqual(sc["unscored_reason"], "missing_critical")
        self.assertIsNone(sc["score"])
        self.assertIsNone(sc["score_pct"])


class TestPerformanceAndStability(unittest.TestCase):
    """בדיקות ביצועים קלילות ויציבות seed."""

    def test_simulate_perf_small(self):
        t0 = _now_ms()
        sim = simulate_exercise(sets=2, reps=10, mode="mixed", noise=0.2)
        t1 = _now_ms()
        self.assertTrue(t1 - t0 < 200, f"simulate too slow: {(t1-t0)} ms")
        # סכימה
        self.assertEqual(sim["sets_total"], 2)
        self.assertEqual(sim["reps_total"], 10)

    def test_analyze_perf_small(self):
        t0 = _now_ms()
        for _ in range(40):
            analyze_exercise(sample_metrics_full())
        t1 = _now_ms()
        self.assertTrue(t1 - t0 < 400, f"analyze too slow: {(t1-t0)} ms")

    def test_sim_seed_stability(self):
        a = simulate_exercise(sets=1, reps=6, mode="good", noise=0.15, seed=42)
        b = simulate_exercise(sets=1, reps=6, mode="good", noise=0.15, seed=42)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), "seed=42 not stable")

    def test_sim_seed_variation(self):
        a = simulate_exercise(sets=1, reps=6, mode="good", noise=0.15, seed=1)
        b = simulate_exercise(sets=1, reps=6, mode="good", noise=0.15, seed=2)
        self.assertNotEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), "different seeds should differ")


class TestUIContract(unittest.TestCase):
    """
    בדיקות 'חוזה UI' – מבטיחות שהשדות הנדרשים ע״י ה-frontend קיימים
    ושאין רגרסיות בשם/טיפוס/טווח.
    """

    def test_ui_ranges_contract(self):
        rep = analyze_exercise(sample_metrics_full())
        ui = rep["ui_ranges"]
        self.assertIn("color_bar", ui)
        bar = ui["color_bar"]
        self.assertIsInstance(bar, list)
        self.assertGreaterEqual(len(bar), 1)
        for rng in bar:
            self.assertIn("label", rng)
            self.assertIn("from_pct", rng)
            self.assertIn("to_pct", rng)
            _assert_pct(self, int(rng["from_pct"]))
            _assert_pct(self, int(rng["to_pct"]))
            self.assertLessEqual(rng["from_pct"], rng["to_pct"])

    def test_scoring_contract(self):
        rep = analyze_exercise(sample_metrics_full())
        sc = rep["scoring"]
        # שמות שדות – לא לשבור!
        for k in ("score", "score_pct", "grade", "quality", "unscored_reason", "criteria", "criteria_breakdown_pct"):
            self.assertIn(k, sc, f"scoring missing key: {k}")
        # טיפוסים
        if sc["score"] is not None:
            self.assertTrue(isinstance(sc["score"], float))
        _assert_pct(self, sc["score_pct"])
        self.assertTrue(isinstance(sc["grade"], str))
        self.assertTrue(isinstance(sc["quality"], str))
        self.assertTrue(isinstance(sc["criteria"], list))
        self.assertTrue(isinstance(sc["criteria_breakdown_pct"], dict))

    def test_criteria_items_contract(self):
        rep = analyze_exercise(sample_metrics_full())
        for c in rep["scoring"]["criteria"]:
            for k in ("id", "available", "score", "score_pct", "reason"):
                self.assertIn(k, c, f"criteria item missing key: {k}")
            self.assertTrue(isinstance(c["id"], str))
            self.assertTrue(isinstance(c["available"], bool))
            if c["score"] is not None:
                _assert_between(self, c["score"], 0.0, 1.0)
            _assert_pct(self, c["score_pct"])


# ======================================================================================
#                                  CLI / Runner glue
# ======================================================================================

def load_tests(loader, tests, pattern):
    """מאפשר להריץ את הקובץ ישירות ע״י unittest discovery."""
    suite = unittest.TestSuite()
    for case in (
        TestSanitize,
        TestSimulateExercise,
        TestAnalyzeExercise,
        TestFuzzAndEdgeCases,
        TestGoldenScenarios,
        TestPerformanceAndStability,
        TestUIContract,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__ == "__main__":
    # הרצה ידנית: מציג גם כותרת־סביבה נוחה
    print("\n=== Offline Test Suite: admin_web/exercise_analyzer.py ===")
    print(f"Python: {sys.version.split()[0]} | Platform: {sys.platform} | CWD: {os.getcwd()}")
    print("=================================================================\n")
    unittest.main(testRunner=RichRunner, verbosity=2)
