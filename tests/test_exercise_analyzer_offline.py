# -*- coding: utf-8 -*-
"""
tests/test_exercise_analyzer_offline.py
בדיקות אוף־ליין ל-admin_web/exercise_analyzer.py:
- sanitize_metrics_payload
- simulate_exercise
- analyze_exercise

הבדיקות תלויות רק במודול exercise_analyzer ו-unittest.
אין תלות בשרת/סטרימר/DB.

הרצה:
    python -m unittest -v tests.test_exercise_analyzer_offline
או:
    python -m unittest discover -s tests -p "test_*.py" -v
"""

from __future__ import annotations
import unittest
import math
import copy
import inspect
from typing import Any, Dict, List

# נייבא את הפונקציות כפי שהגדרת בקובץ שלך
from admin_web.exercise_analyzer import (
    sanitize_metrics_payload,
    simulate_exercise,
    analyze_exercise,
)


# ---------- עזר: עטיפה לסימולציה (תואם חתימה קיימת) ----------
def sim_call(**kwargs):
    """
    העטיפה הזו מעבירה ל-simulate_exercise רק פרמטרים שהחתימה שלו תומכת בהם,
    כדי להישאר תואמים לגרסאות שונות.
    """
    sig = inspect.signature(simulate_exercise)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return simulate_exercise(**allowed)


# ---------- עזר: בדיקות סכמה מפורטות ----------
def assert_key(
    tc: unittest.TestCase,
    obj: Dict[str, Any],
    key: str,
    expected_type,
    allow_none: bool = False,
    ctx: str = "",
):
    tc.assertIn(key, obj, f"{ctx}: key '{key}' missing")
    val = obj.get(key)
    if allow_none and (val is None):
        return
    tc.assertIsInstance(val, expected_type, f"{ctx}: key '{key}' wrong type (got {type(val).__name__})")


def assert_pct_0_100(
    tc: unittest.TestCase,
    val: Any,
    key_path: str,
    ctx: str = "",
    allow_none: bool = False,
):
    if val is None:
        tc.assertTrue(allow_none, f"{ctx}: '{key_path}' is None but allow_none=False")
        return
    tc.assertIsInstance(val, int, f"{ctx}: '{key_path}' must be int percentage or None")
    tc.assertGreaterEqual(val, 0, f"{ctx}: '{key_path}' < 0")
    tc.assertLessEqual(val, 100, f"{ctx}: '{key_path}' > 100")


def assert_score_0_1(
    tc: unittest.TestCase,
    val: Any,
    key_path: str,
    ctx: str = "",
    allow_none: bool = False,
):
    if val is None:
        tc.assertTrue(allow_none, f"{ctx}: '{key_path}' is None but allow_none=False")
        return
    tc.assertIsInstance(val, (int, float), f"{ctx}: '{key_path}' must be float in [0..1] or None")
    f = float(val)
    tc.assertGreaterEqual(f, 0.0, f"{ctx}: '{key_path}' < 0.0")
    tc.assertLessEqual(f, 1.0, f"{ctx}: '{key_path}' > 1.0")


# ---------- טסטים לסניטציה ----------
class TestSanitizeMetrics(unittest.TestCase):

    def test_sanitize_basic_numbers_and_strings(self):
        raw = {
            "torso_vs_vertical_deg": "12.5",
            "knee_angle_left": 150,
            "rep_time_s": "2",
            "view.mode": "front",
            "exercise.id": "squat.bodyweight",
            "weird": "abc",
            "bool_true": "true",
            "bool_false": "False",
            "nan": "NaN",
        }
        out = sanitize_metrics_payload(raw)

        self.assertIn("torso_vs_vertical_deg", out)
        self.assertIsInstance(out["torso_vs_vertical_deg"], float)
        self.assertAlmostEqual(out["torso_vs_vertical_deg"], 12.5, places=6)

        self.assertIn("knee_angle_left", out)
        self.assertIsInstance(out["knee_angle_left"], float)
        self.assertEqual(out["knee_angle_left"], 150.0)

        # מספר כטקסט
        self.assertIn("rep_time_s", out)
        self.assertIsInstance(out["rep_time_s"], float)
        self.assertEqual(out["rep_time_s"], 2.0)

        # שדות טקסט מותרים
        self.assertEqual(out.get("view.mode"), "front")
        self.assertEqual(out.get("exercise.id"), "squat.bodyweight")

        # טענות בוליאניות
        self.assertIn("bool_true", out)
        self.assertTrue(out["bool_true"])
        self.assertIn("bool_false", out)
        self.assertFalse(out["bool_false"])

        # "abc" לא עובר המרה למספר ולכן מושמט
        self.assertNotIn("weird", out)

        # NaN לא אמור להיכנס – הסניטציה מתעלמת
        self.assertNotIn("nan", out)

    def test_sanitize_booleans_and_integers(self):
        raw = {
            "rep.phase": "down",
            "pose.ok": True,
            "count": 3,
            "bad": object(),
        }
        out = sanitize_metrics_payload(raw)
        self.assertEqual(out.get("rep.phase"), "down")
        self.assertTrue(out.get("pose.ok"))
        self.assertEqual(out.get("count"), 3.0)  # נשמר כ-float
        self.assertNotIn("bad", out)

    def test_sanitize_filters_non_finite(self):
        raw = {
            "x": float("inf"),
            "y": float("-inf"),
            "z": float("nan"),
            "ok": 1.23,
        }
        out = sanitize_metrics_payload(raw)
        self.assertNotIn("x", out)
        self.assertNotIn("y", out)
        self.assertNotIn("z", out)
        self.assertIn("ok", out)
        self.assertEqual(out["ok"], 1.23)


# ---------- טסטים לסימולציה ----------
class TestSimulateExercise(unittest.TestCase):

    def _check_sim_schema(self, sim: Dict[str, Any], ctx: str = ""):
        self.assertIsInstance(sim, dict, f"{ctx}: simulate_exercise must return dict")
        self.assertIn("ok", sim, f"{ctx}: missing 'ok'")
        self.assertIn("sets", sim, f"{ctx}: missing 'sets'")
        self.assertIsInstance(sim["sets"], list, f"{ctx}: 'sets' must be list")

        # פרטי רמות על
        if "sets_total" in sim:
            self.assertIsInstance(sim["sets_total"], int, f"{ctx}: 'sets_total' must be int")
            self.assertGreaterEqual(sim["sets_total"], 1, f"{ctx}: 'sets_total' < 1")
        if "reps_total" in sim:
            self.assertIsInstance(sim["reps_total"], int, f"{ctx}: 'reps_total' must be int")
            self.assertGreaterEqual(sim["reps_total"], 1, f"{ctx}: 'reps_total' < 1")

        # לכל סט
        for i, st in enumerate(sim["sets"], start=1):
            sctx = f"{ctx}/set[{i}]"
            assert_key(self, st, "set", int, ctx=sctx)
            if "set_score" in st:
                assert_score_0_1(self, st["set_score"], "set_score", ctx=sctx, allow_none=False)
            if "set_score_pct" in st:
                assert_pct_0_100(self, st["set_score_pct"], "set_score_pct", ctx=sctx, allow_none=False)

            assert_key(self, st, "reps", list, ctx=sctx)
            self.assertGreater(len(st["reps"]), 0, f"{sctx}: 'reps' empty")

            for j, r in enumerate(st["reps"], start=1):
                rctx = f"{sctx}/rep[{j}]"
                assert_key(self, r, "rep", int, ctx=rctx)
                if "score" in r:
                    assert_score_0_1(self, r["score"], "score", ctx=rctx, allow_none=False)
                if "score_pct" in r:
                    assert_pct_0_100(self, r["score_pct"], "score_pct", ctx=rctx, allow_none=False)
                # הערות אופציונליות
                if "notes" in r:
                    self.assertIsInstance(r["notes"], list, f"{rctx}: 'notes' must be list")

    def test_simulate_defaults_schema(self):
        sim = sim_call()  # שימוש בחתימה בפועל
        self._check_sim_schema(sim, "defaults")

    def test_simulate_bounds_and_clamping(self):
        sim = sim_call(sets=999, reps=999, mean_score=-1, std=999)
        # אמור לקצץ לטווחים חוקיים (1..10 sets, 1..30 reps, score ב-[0..1], std ב-[0..0.5])
        self._check_sim_schema(sim, "clamped")
        self.assertGreaterEqual(sim.get("sets_total", 1), 1, "sets_total clamp failed")
        self.assertLessEqual(sim.get("sets_total", 10), 10, "sets_total clamp failed")
        self.assertGreaterEqual(sim.get("reps_total", 1), 1, "reps_total clamp failed")
        self.assertLessEqual(sim.get("reps_total", 30), 30, "reps_total clamp failed")

        # בדיקה שכל הציונים בין 0..100
        for st in sim["sets"]:
            if "set_score" in st:
                self.assertGreaterEqual(float(st["set_score"]), 0.0)
                self.assertLessEqual(float(st["set_score"]), 1.0)
            if "set_score_pct" in st:
                self.assertGreaterEqual(int(st["set_score_pct"]), 0)
                self.assertLessEqual(int(st["set_score_pct"]), 100)
            for r in st["reps"]:
                self.assertGreaterEqual(float(r["score"]), 0.0)
                self.assertLessEqual(float(r["score"]), 1.0)
                self.assertGreaterEqual(int(r["score_pct"]), 0)
                self.assertLessEqual(int(r["score_pct"]), 100)

    def test_simulate_is_deterministic(self):
        # המימוש משתמש ב-random.Random(42) => אותה תוצאה בכל ריצה
        sim1 = sim_call(sets=2, reps=8, mean_score=0.8, std=0.15)
        sim2 = sim_call(sets=2, reps=8, mean_score=0.8, std=0.15)
        self.assertEqual(sim1, sim2, "simulate_exercise should be deterministic with seeded RNG")

    def test_simulate_variance_changes_with_std(self):
        # std קטן => פיזור קטן; std גדול => פיזור גדול
        sim_small = sim_call(sets=1, reps=12, mean_score=0.85, std=0.01)
        sim_big   = sim_call(sets=1, reps=12, mean_score=0.85, std=0.50)

        def variance_from_sim(sim):
            vals = []
            for st in sim["sets"]:
                for r in st["reps"]:
                    vals.append(float(r["score"]))
            mean = sum(vals) / max(1, len(vals))
            var = sum((x - mean) ** 2 for x in vals) / max(1, len(vals))
            return var

        v_small = variance_from_sim(sim_small)
        v_big   = variance_from_sim(sim_big)
        self.assertGreater(v_big, v_small, f"expected variance(std=0.50) > variance(std=0.01), got {v_big} <= {v_small}")


# ---------- טסטים ל-analyze_exercise ----------
class TestAnalyzeExercise(unittest.TestCase):

    def _check_report_schema(self, rep: Dict[str, Any], ctx: str = ""):
        self.assertIsInstance(rep, dict, f"{ctx}: report must be dict")
        assert_key(self, rep, "exercise", dict, ctx=ctx)
        assert_key(self, rep, "scoring", dict, ctx=ctx)
        # hints יכול להיות רשימה או לא קיים — אבל אם קיים, שיהיה list
        if "hints" in rep:
            self.assertIsInstance(rep["hints"], list, f"{ctx}: 'hints' must be list")

        ex = rep["exercise"]
        assert_key(self, ex, "id", (str,), ctx=f"{ctx}/exercise")

        sc = rep["scoring"]
        # score ו-score_pct יכולים להיות None (unscored)
        if "score" in sc:
            if sc["score"] is not None:
                assert_score_0_1(self, sc["score"], "scoring.score", ctx=ctx, allow_none=True)
        if "score_pct" in sc:
            assert_pct_0_100(self, sc["score_pct"], "scoring.score_pct", ctx=ctx, allow_none=True)

        # grade/quality אופציונליים; אם קיימים – מחרוזות
        if "grade" in sc and sc["grade"] is not None:
            self.assertIsInstance(sc["grade"], str, f"{ctx}: scoring.grade must be str or None")
        if "quality" in sc and sc["quality"] is not None:
            self.assertIsInstance(sc["quality"], str, f"{ctx}: scoring.quality must be str or None")

        # unscored_reason אופציונלי; אם קיים – str או None
        if "unscored_reason" in sc:
            self.assertTrue(
                (sc["unscored_reason"] is None) or isinstance(sc["unscored_reason"], str),
                f"{ctx}: scoring.unscored_reason must be str or None"
            )

        # criteria — רשימה של אובייקטים {id, available, score?, score_pct?, reason?}
        self.assertIn("criteria", sc, f"{ctx}: scoring.criteria missing")
        self.assertIsInstance(sc["criteria"], list, f"{ctx}: scoring.criteria must be list")

        for idx, c in enumerate(sc["criteria"], start=1):
            cctx = f"{ctx}/criteria[{idx}]"
            assert_key(self, c, "id", (str,), ctx=cctx)
            assert_key(self, c, "available", (bool,), ctx=cctx)
            # score/score_pct/ reason אופציונליים
            if "score" in c and c["score"] is not None:
                assert_score_0_1(self, c["score"], "criteria.score", ctx=cctx, allow_none=True)
            if "score_pct" in c and c["score_pct"] is not None:
                assert_pct_0_100(self, c["score_pct"], "criteria.score_pct", ctx=cctx, allow_none=True)
            if "reason" in c and c["reason"] is not None:
                self.assertIsInstance(c["reason"], str, f"{cctx}: reason must be str or None")

    def test_analyze_no_metrics_returns_unscored_demo(self):
        rep = analyze_exercise({})  # אין מטריקות -> דמו לא מדורג
        self._check_report_schema(rep, "no_metrics")
        sc = rep["scoring"]
        self.assertIsNone(sc["score"], "expected score=None in unscored flow OR demo branch")
        self.assertIsNone(sc["score_pct"], "expected score_pct=None in unscored flow OR demo branch")
        self.assertIsInstance(sc.get("unscored_reason"), (str, type(None)), "unscored_reason must be str or None")
        self.assertIn("criteria", sc)
        # לפחות עומק/ברכיים מופיעים
        crit_ids = {c["id"] for c in sc["criteria"]}
        self.assertIn("depth", crit_ids, "expected 'depth' in criteria")
        self.assertIn("knees", crit_ids, "expected 'knees' in criteria")

    def test_analyze_with_good_metrics_returns_scored(self):
        # מטריקות "נקיות" שאמורות להניב ציון טוב
        metrics = {
            "torso_vs_vertical_deg": 5.0,   # גב כמעט אנכי
            "knee_angle_left": 130.0,
            "knee_angle_right": 130.0,
            "hip_left_deg": 100.0,
            "hip_right_deg": 100.0,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.6,
        }
        payload = {"metrics": metrics, "exercise": {"id": "squat.bodyweight"}}
        rep = analyze_exercise(payload)
        self._check_report_schema(rep, "good_metrics")

        sc = rep["scoring"]
        # score קיים ובתחום
        self.assertIsInstance(sc["score"], float)
        assert_score_0_1(self, sc["score"], "scoring.score", ctx="good_metrics", allow_none=False)

        # יש קורלציה בין score ו-score_pct
        if sc["score_pct"] is not None:
            expected_pct = int(round(float(sc["score"]) * 100))
            self.assertEqual(
                sc["score_pct"], expected_pct,
                f"score_pct should equal round(score*100). got {sc['score_pct']} != {expected_pct}"
            )

        # הקריטריונים זמינים ועם ציונים טובים יחסית
        by_id = {c["id"]: c for c in sc["criteria"]}
        for cid in ("depth", "knees", "torso_angle", "stance_width", "tempo"):
            self.assertIn(cid, by_id, f"criteria '{cid}' missing")
            self.assertTrue(by_id[cid]["available"], f"criteria '{cid}' expected available=True")
            # אם יש score_pct – נצפה ל-70+ במטריקות הטובות
            sp = by_id[cid].get("score_pct")
            if sp is not None:
                self.assertGreaterEqual(sp, 70, f"criteria '{cid}' expected >=70, got {sp}")

    def test_analyze_with_bad_depth_and_valgus(self):
        # עומק חלש + ולגוס — אמור להוריד ציון ולאכלס רמזים מתאימים
        metrics = {
            "torso_vs_vertical_deg": 20.0,  # גב קצת קדימה
            "knee_angle_left": 165.0,       # כמעט ישר
            "knee_angle_right": 150.0,      # אסימטרי
            "hip_left_deg": 140.0,
            "hip_right_deg": 140.0,
            "feet_w_over_shoulders_w": 1.6,
            "rep_time_s": 0.7,              # מהיר מידי
        }
        payload = {"metrics": metrics, "exercise": {"id": "squat.bodyweight"}}
        rep = analyze_exercise(payload)
        self._check_report_schema(rep, "bad_depth_valgus")

        sc = rep["scoring"]
        self.assertIsNone(sc.get("unscored_reason"), "should be scored (not unscored)")

        by_id = {c["id"]: c for c in sc["criteria"]}

        # עומק נמוך => reason shallow_depth
        if "depth" in by_id:
            reason = by_id["depth"].get("reason")
            sp = by_id["depth"].get("score_pct")
            # ייתכן אחד משני המצבים: או reason=shallow_depth, או ציון נמוך
            self.assertTrue(
                (reason == "shallow_depth") or (sp is not None and sp < 70),
                f"depth expected shallow/low. got reason={reason}, score_pct={sp}"
            )

        # ברכיים — ולגוס (הפרש זוויות גדול)
        if "knees" in by_id:
            k_reason = by_id["knees"].get("reason")
            self.assertIn(k_reason, (None, "valgus"))
            # במטריקות הללו נצפה שלפחות ציון נמוך
            k_sp = by_id["knees"].get("score_pct")
            if k_sp is not None:
                self.assertLess(k_sp, 80, f"knees expected < 80, got {k_sp}")

        # hints — רמזים טכניים
        hints = rep.get("hints", [])
        # לא נכפה בדיוק את הטקסט (שפה/ניסוח יכולים להשתנות), אבל נבדוק שיש לפחות 1–2 רמזים
        self.assertIsInstance(hints, list, "hints must be list")
        self.assertGreater(len(hints), 0, "expected at least 1 hint for bad metrics")

    def test_analyze_handles_partial_metrics(self):
        # מטריקות חלקיות — חלק מהקריטריונים לא זמינים
        metrics = {
            "torso_vs_vertical_deg": 15.0,  # יש טורסו
            # אין ברכיים/ירכיים
            "feet_w_over_shoulders_w": 1.4,
            # אין tempo
        }
        payload = {"metrics": metrics, "exercise": {"id": "squat.bodyweight"}}
        rep = analyze_exercise(payload)
        self._check_report_schema(rep, "partial_metrics")

        # חלק מהקריטריונים לא זמינים
        sc = rep["scoring"]
        crit = sc["criteria"]
        unavailable = [c for c in crit if not c.get("available")]
        self.assertGreater(len(unavailable), 0, "expected some unavailable criteria with partial metrics")

        # דאגה: אם לא היה ניתן לנקד כלל — יכול להיות unscored. אם כן מוקצה ציון — תקין.
        if sc["score"] is None:
            self.assertIsInstance(sc.get("unscored_reason"), str, "expected unscored_reason when score=None")

    def test_analyze_is_pure_and_not_mutating_payload(self):
        # נוודא שהפונקציה לא משנה את ה-payload שהעברנו
        original = {
            "metrics": {
                "torso_vs_vertical_deg": 8.0,
                "knee_angle_left": 140.0,
                "knee_angle_right": 140.0,
                "hip_left_deg": 100.0,
                "hip_right_deg": 100.0,
                "feet_w_over_shoulders_w": 1.25,
                "rep_time_s": 1.8,
            },
            "exercise": {"id": "squat.bodyweight"},
        }
        payload = copy.deepcopy(original)
        _ = analyze_exercise(payload)

        self.assertEqual(payload, original, "analyze_exercise must not mutate the input payload")

    def test_analyze_score_pct_matches_score(self):
        # אם מתקבל גם score וגם score_pct — שניהם חייבים להתאים (בעיגול int)
        metrics = {
            "torso_vs_vertical_deg": 10.0,
            "knee_angle_left": 135.0,
            "knee_angle_right": 135.0,
            "hip_left_deg": 100.0,
            "hip_right_deg": 100.0,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.5,
        }
        rep = analyze_exercise({"metrics": metrics})
        sc = rep["scoring"]
        if sc.get("score") is not None and sc.get("score_pct") is not None:
            expected_pct = int(round(float(sc["score"]) * 100))
            self.assertEqual(sc["score_pct"], expected_pct, "score_pct != round(score*100)")

    def test_analyze_handles_extreme_values_gracefully(self):
        # ערכים קיצוניים (אבל סופיים) — הפונקציה צריכה להתמודד איתם, לצמצם/לנקד בהתאם
        metrics = {
            "torso_vs_vertical_deg": 9999.0,    # גדול מאוד -> יצור ציון נמוך מאוד לטורסו
            "knee_angle_left": -9999.0,        # קצה נגדי
            "knee_angle_right": 9999.0,
            "hip_left_deg": -999.0,
            "hip_right_deg": 999.0,
            "feet_w_over_shoulders_w": -10.0,
            "rep_time_s": 100.0,
        }
        rep = analyze_exercise({"metrics": metrics})
        self._check_report_schema(rep, "extreme_values")

        # ודא שאיננו נופלים. לרוב זה יניב ציונים מאוד נמוכים או unscored.
        sc = rep["scoring"]
        # לכל היותר — score None עם unscored_reason
        if sc["score"] is not None:
            assert_score_0_1(self, sc["score"], "scoring.score", ctx="extreme_values", allow_none=False)

    def test_analyze_with_aliases_are_respected(self):
        # וידוא שאליאסים עובדים (לפי ההגדרות בקוד: knee_angle_left_deg וכו')
        metrics = {
            "torso_vs_vertical_deg": 7.0,
            "knee_angle_left_deg": 132.0,  # ALIAS של knee_angle_left
            "knee_angle_right_deg": 132.0, # ALIAS של knee_angle_right
            "hip_left_deg": 100.0,
            "hip_right_deg": 100.0,
            "feet_w_over_shoulders_w": 1.2,
            "rep_time_s": 1.6,
        }
        rep = analyze_exercise({"metrics": metrics})
        self._check_report_schema(rep, "aliases")

        sc = rep["scoring"]
        by_id = {c["id"]: c for c in sc["criteria"]}
        # הברכיים אמורות להיות זמינות
        self.assertTrue(by_id["knees"]["available"], "knees should be available when aliases present (knee_angle_*_deg)")
        # ואם יש לנו מטריקות טובות — ציון סביר
        sp = by_id["knees"].get("score_pct")
        if sp is not None:
            self.assertGreaterEqual(sp, 70, f"knees expected >=70 with symmetric angles, got {sp}")


if __name__ == "__main__":
    # מאפשר הרצה ישירה של הקובץ
    unittest.main(verbosity=2)
