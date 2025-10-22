# -*- coding: utf-8 -*-
# tools/tests/test_reps_sets_offline.py
# בדיקות יחידה למנוע החזרות (reps) + מונה סטים (set_counter)
#
# עקרונות:
# - משתמשים ב-exercise_cfg דטרמיניסטי: ema_alpha=1.0, phase_delta קטן, ספים ברורים.
# - בכל חזרה: שינוי כיוון (turn), השהיה ≥ min_turn_ms על ה-turn, וסגירה קרובה ל-top_ref.
# - good/partial מנפיקים rep_event; fast/slow לא מנפיקים rep_event אבל כן מגדירים rep.quality.

import unittest

from exercise_engine.segmenter.reps import update_rep_state, reset_state
from exercise_engine.segmenter.set_counter import SetCounter

CFG = {
    "rep_signal": {
        # עובדים על מינימום זווית ברכיים כדי לדמות סקוואט/כפיפה
        "source": "value|min|knee_left_deg,knee_right_deg",
        "target": "min",
        # מבטלים החלקה כדי למנוע “זליגה” בין דגימות
        "ema_alpha": 1.0,
        "thresholds": {
            # קטן כדי לזהות שינוי כיוון מהר
            "phase_delta": 1.0,
            # פרמטרי זמן: fast < 400ms ; slow > 6000ms (לא נשתמש איטי)
            "min_rep_ms": 400,
            "max_rep_ms": 6000,
            # צריך לעמוד על ההיפוך לפחות 80ms
            "min_turn_ms": 80,
            # ספי ROM
            "min_rom_good": 18.0,   # מעל זה → good
            "min_rom_partial": 10.0 # בין 10 ל-18 → partial
        }
    }
}

def step(payload, t):
    """עוזר קצר לשיחות ל-API של reps."""
    return update_rep_state(payload, now_ms=t, exercise_cfg=CFG)

# ─────────────────────────── Reps Engine ───────────────────────────

class TestRepsEngine(unittest.TestCase):
    def setUp(self):
        reset_state()

    def test_bootstrap_first_sample_is_start(self):
        """דגימה ראשונה תמיד start וללא rep_event."""
        updates, event = step({"knee_left_deg": 90, "knee_right_deg": 92}, 0)
        self.assertIsNone(event)
        self.assertEqual(updates["rep.state"], "start")

    def test_towards_on_second_sample(self):
        """שתי דגימות—השנייה יורדת לכיוון היעד → towards."""
        step({"knee_left_deg": 90, "knee_right_deg": 92}, 0)         # start
        updates, _ = step({"knee_left_deg": 70, "knee_right_deg": 72}, 120)
        self.assertEqual(updates["rep.state"], "towards")

    def test_full_good_rep_event(self):
        """
        חזרה מלאה עם ROM≈30° ובזמן ~560ms:
        start→towards→turn(שהייה≥80ms)→away→סגירה קרובה → rep_event עם quality='good'.
        """
        t = 0
        step({"knee_left_deg": 90, "knee_right_deg": 92}, t)   # start @0

        t += 120  # 120ms
        step({"knee_left_deg": 60, "knee_right_deg": 62}, t)   # towards (ROM לכיוון המינ')

        t += 120  # 240ms
        step({"knee_left_deg": 61, "knee_right_deg": 63}, t)   # detect turn

        t += 100  # 340ms (>=80ms על turn)
        step({"knee_left_deg": 72, "knee_right_deg": 74}, t)   # away

        t += 220  # 560ms total → בתוך חלון good (>=400ms)
        updates, rep_event = step({"knee_left_deg": 90, "knee_right_deg": 92}, t)  # close near top_ref

        self.assertIsNotNone(rep_event, "ציפינו ל-rep_event בסוף חזרה מלאה.")
        self.assertEqual(rep_event["quality"], "good")
        self.assertGreaterEqual(rep_event["rom"], 18.0)
        self.assertEqual(updates["rep.state"], "start")

    def test_partial_rep_event(self):
        """
        ROM חלקי ≈12° (בין 10 ל-18) וזמן ~560ms → rep_event עם quality='partial'.
        """
        t = 0
        step({"knee_left_deg": 90, "knee_right_deg": 92}, t)   # start

        t += 120
        step({"knee_left_deg": 78, "knee_right_deg": 80}, t)   # towards (ROM≈12°)

        t += 120
        step({"knee_left_deg": 79, "knee_right_deg": 81}, t)   # turn

        t += 120
        step({"knee_left_deg": 83, "knee_right_deg": 85}, t)   # away

        t += 200  # 560ms total
        updates, rep_event = step({"knee_left_deg": 90, "knee_right_deg": 92}, t)  # close

        self.assertIsNotNone(rep_event, "partial אמור לייצר rep_event.")
        self.assertEqual(rep_event["quality"], "partial")
        self.assertGreaterEqual(rep_event["rom"], 10.0)
        self.assertLess(rep_event["rom"], 18.0)
        self.assertEqual(updates["rep.state"], "start")

    def test_fast_rep_is_rejected_no_event(self):
        """
        חזרה מהירה מדי: rep_ms < 400ms → אין rep_event, אך updates['rep.quality']=='fast'.
        עדיין מקפידים על turn (עם השהייה ≥80ms) וסגירה קרובה ל-top_ref כדי שהאיכות תיכתב.
        """
        t = 0
        step({"knee_left_deg": 90, "knee_right_deg": 92}, t)   # start

        t += 100  # 100ms
        step({"knee_left_deg": 60, "knee_right_deg": 62}, t)   # towards

        t += 80   # 180ms
        step({"knee_left_deg": 61, "knee_right_deg": 63}, t)   # turn

        t += 100  # 280ms (>=80ms על turn)
        step({"knee_left_deg": 72, "knee_right_deg": 74}, t)   # away

        t += 60   # 340ms total (< 400ms) → fast
        updates, rep_event = step({"knee_left_deg": 90, "knee_right_deg": 92}, t)  # close

        self.assertIsNone(rep_event, "מהיר מדי → לא מנפיקים rep_event.")
        self.assertEqual(updates.get("rep.quality"), "fast", "במקרה כזה quality צריך להיות 'fast'.")

    def test_auto_signal_warning_on_no_cfg_source(self):
        """בדיקה טכנית: אם אין source מפורש, מתקבלת אזהרה (כאן כן יש source, ולכן לא אמורה להופיע)."""
        updates, _ = update_rep_state({"knee_left_deg": 90, "knee_right_deg": 92}, now_ms=0, exercise_cfg=CFG)
        self.assertFalse(updates.get("rep.warnings.auto_target_used", False),
                         "כאן יש source מפורש, לכן לא אמורה להיות אזהרת auto_target_used.")


# ─────────────────────────── Set Counter ───────────────────────────

class TestSetCounter(unittest.TestCase):
    def test_set_valid_with_rep_event(self):
        """סט עם min_reps=1: חזרה אחת טובה + set.end → ok=True ו-reps=1."""
        sc = SetCounter(min_reps=1, reset_timeout_s=7.0)
        t0 = 1_000
        sc.handle_signals({"set.begin": True}, t0)
        sc.update({"rep_id": 1, "timing_s": 1.2, "rom": 20.0, "quality": "good"}, t0 + 1200)
        closed = sc.handle_signals({"set.end": True}, t0 + 1300)
        self.assertIsNotNone(closed)
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["reps"], 1)

    def test_set_forced_end_even_without_reps(self):
        """set.end (forced=True) → ok=True גם ללא חזרות (עצירה ידנית)."""
        sc = SetCounter(min_reps=3, reset_timeout_s=7.0)
        t0 = 10_000
        sc.handle_signals({"set.begin": True}, t0)
        closed = sc.handle_signals({"set.end": True}, t0 + 500)
        self.assertIsNotNone(closed)
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["reps"], 0)

    def test_set_timeout_without_reps(self):
        """ללא rep_event עד timeout → סגירת סט אוטומטית עם ok=False ו-reps=0."""
        sc = SetCounter(min_reps=1, reset_timeout_s=1.5)
        t0 = 0
        sc.begin_set(t0)
        closed = sc.update(None, t0 + 1600)
        self.assertIsNotNone(closed)
        self.assertFalse(closed["ok"])
        self.assertEqual(closed["reps"], 0)

    def test_begin_then_rep_then_timeout(self):
        """סט עם חזרה אחת ואז חוסר פעילות עד timeout → סגירה אוטומטית עם ok=True ו-reps=1."""
        sc = SetCounter(min_reps=1, reset_timeout_s=1.0)
        t0 = 50_000
        sc.begin_set(t0)
        sc.update({"rep_id": 1, "timing_s": 1.1, "rom": 16.0, "quality": "good"}, t0 + 300)
        closed = sc.update(None, t0 + 1400)
        self.assertIsNotNone(closed)
        self.assertTrue(closed["ok"])
        self.assertEqual(closed["reps"], 1)

    def test_inject_fields(self):
        """וידוא הזרקת שדות מצב הסט ליעד."""
        sc = SetCounter(min_reps=1, reset_timeout_s=7.0)
        t0 = 0
        sc.begin_set(t0)
        sc.update({"rep_id": 1, "timing_s": 1.2, "rom": 20.0, "quality": "good"}, t0 + 1300)
        target = {}
        sc.inject(target)
        self.assertTrue(target["rep.set_active"])
        self.assertEqual(target["rep.set_index"], 1)
        self.assertEqual(target["rep.set_reps"], 1)
        self.assertEqual(target["rep.set_total"], 0)


if __name__ == "__main__":
    unittest.main()
