# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Stage 7 — Deep Probe for Grace + Availability
#
# מה בודקים?
#   • גרייס עובד מייד אחרי switch (unscored_reason=grace_period).
#   • אחרי שהגרייס מסתיים:
#       - מסלול BAD: אם עדיין חסרים מדדים לקריטריון קריטי (depth), נקבל missing_critical: depth.
#       - מסלול GOOD: אם נוסיף את המפתחות הנדרשים, נקבל ציון רגיל.
#
# למה זה חשוב?
#   הבדיקה מדפיסה:
#     1) canonical אחרי normalizer (מה באמת נכנס למנוע)
#     2) availability לכל קריטריון (available/missing/reason)
#     3) הצצה ל-scoring: score_pct/grade/unscored_reason
#
# איך לגרום לגרייס להתנהג?
#   הבדיקה עושה monkeypatch ל-runtime.cls_pick:
#     - pick_first  -> "squat.bodyweight" (לפני ההחלפה)
#     - pick_switch -> "squat.base" עם last_switch_ms=now (מפעיל גרייס)
#     - pick_stay   -> "squat.base" ללא last_switch_ms (לא אמור להפעיל גרייס שוב)
#
# הפעלה:
#   $env:EXR_GRACE_MS="1000"
#   python run_stage7_deep_probe.py
# -----------------------------------------------------------------------------

from __future__ import annotations
import json, time, os
from pathlib import Path
from types import SimpleNamespace

from exercise_engine.registry.loader import load_library
import exercise_engine.runtime.runtime as rt
from exercise_engine.runtime.runtime import run_once
from exercise_engine.runtime.validator import evaluate_availability

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "exercise_library"

def pretty(obj): return json.dumps(obj, ensure_ascii=False, indent=2)

def _dump_core(report: dict, title: str):
    print("="*80)
    print(title)
    print("="*80)
    ex = (report.get("exercise") or {}).get("id")
    sc = (report.get("scoring") or {})
    print(pretty({
        "exercise_id": ex,
        "unscored_reason": sc.get("unscored_reason"),
        "score_pct": sc.get("score_pct"),
        "grade": sc.get("grade")
    }))
    print()

def _dump_availability(ex_def, canonical: dict, title: str):
    print("-"*80)
    print(title)
    print("-"*80)
    avail = evaluate_availability(ex_def, canonical) if ex_def else {}
    # נחלץ לכל קריטריון: available/missing/reason
    rows = {}
    for name, info in (ex_def.criteria or {}).items():
        r = avail.get(name, {})
        rows[name] = {
            "available": bool(r.get("available", False)),
            "missing": list(r.get("missing") or []),
            "reason": r.get("reason")
        }
    print("availability (by criterion):")
    print(pretty(rows))
    print()

def _dump_canonical(canon: dict, keys_of_interest=None, title="canonical (selected)"):
    print("-"*80)
    print(title)
    print("-"*80)
    if keys_of_interest is None:
        # הדפסה מלאה (זהירה – רק המפתחות העיקריים שלנו)
        keys_of_interest = [
            "torso_forward_deg",
            "knee_left_deg", "knee_right_deg",
            "hip_left_deg", "hip_right_deg",
            "features.stance_width_ratio",
            "rep.timing_s",
            "rep.phase", "rep.in_rep_window", "rep.freeze_active",
        ]
    out = {k: canon.get(k) for k in keys_of_interest}
    print(pretty(out))
    print()

def main():
    print("\n" + "="*80)
    print("Stage 7 — Deep Probe for Grace + Availability")
    print("="*80 + "\n")

    lib = load_library(LIB)
    print(f"✓ ספרייה נטענה: {lib.version}\n")

    # נשמור את פונקציית הבחירה המקורית
    original_cls_pick = rt.cls_pick

    # payload בסיסי (שימו לב: אין בו ברכיים → depth יחשב חסר אם קריטי)
    f_common = {
        "torso_vs_vertical_deg": 12.0,     # ↦ torso_forward_deg
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.15,   # ↦ features.stance_width_ratio
        "rep_time_s": 1.3,                 # ↦ rep.timing_s
    }

    f1 = dict(f_common)  # לפני ההחלפה
    f2 = dict(f_common)  # אחרי ההחלפה (גרייס אמור לפעול)
    f3_bad  = dict(f_common)  # אחרי הגרייס — בלי ברכיים → עדיין חסר depth
    f3_good = dict(f_common)  # אחרי הגרייס — נוסיף ברכיים → אמור להיספר

    # הוספת ברכיים לגרסה "הטובה"
    f3_good.update({
        "knee_angle_left": 145.0,   # ↦ knee_left_deg
        "knee_angle_right": 151.0,  # ↦ knee_right_deg
    })

    # מימושי pick מדומים
    def pick_first(canonical, library, prev_state=None, freeze_active=False, fallback_bodyweight_id=None):
        now_ms = int(time.time()*1000)
        return SimpleNamespace(
            status="ok",
            exercise_id="squat.bodyweight",
            family="squat",
            equipment_inferred="none",
            confidence=0.9,
            reason="best_match_rules",
            stability=SimpleNamespace(kept_previous=False, margin=0.5, freeze_active=False, last_switch_ms=None),
            candidates=[],
            state=SimpleNamespace(prev_exercise_id="squat.bodyweight",
                                  confidence_ema=0.9,
                                  low_conf_since_ms=None,
                                  last_switch_ms=None),
            diagnostics=[{"type":"debug","message":"pick_first","ts":now_ms}]
        )

    # החלפה אמיתית -> מפעיל גרייס
    def pick_switch(canonical, library, prev_state=None, freeze_active=False, fallback_bodyweight_id=None):
        now_ms = int(time.time()*1000)
        return SimpleNamespace(
            status="ok",
            exercise_id="squat.base",
            family="squat",
            equipment_inferred="none",
            confidence=0.85,
            reason="best_match_rules",
            stability=SimpleNamespace(kept_previous=False, margin=0.6, freeze_active=False, last_switch_ms=now_ms),
            candidates=[],
            state=SimpleNamespace(prev_exercise_id="squat.base",
                                  confidence_ema=0.85,
                                  low_conf_since_ms=None,
                                  last_switch_ms=now_ms),
            diagnostics=[{"type":"debug","message":"pick_switch","ts":now_ms}]
        )

    # נשארים על אותו תרגיל (base) – אין last_switch_ms חדש
    def pick_stay(canonical, library, prev_state=None, freeze_active=False, fallback_bodyweight_id=None):
        now_ms = int(time.time()*1000)
        return SimpleNamespace(
            status="ok",
            exercise_id="squat.base",
            family="squat",
            equipment_inferred="none",
            confidence=0.88,
            reason="best_match_rules",
            stability=SimpleNamespace(kept_previous=True, margin=0.6, freeze_active=False, last_switch_ms=None),
            candidates=[],
            state=SimpleNamespace(prev_exercise_id="squat.base",
                                  confidence_ema=0.88,
                                  low_conf_since_ms=None,
                                  last_switch_ms=None),
            diagnostics=[{"type":"debug","message":"pick_stay","ts":now_ms}]
        )

    try:
        # REPORT #1 — לפני ההחלפה
        rt.cls_pick = pick_first
        r1 = run_once(raw_metrics=f1, library=lib, exercise_id=None, payload_version="1.0")
        _dump_core(r1, "REPORT #1 (before switch)")
        _dump_canonical(r1.get("measurements") or {}, title="canonical after normalizer (R1)")
        ex1 = lib.index_by_id.get((r1.get("exercise") or {}).get("id"))
        _dump_availability(ex1, r1.get("measurements") or {}, "availability snapshot (R1)")

        # REPORT #2 — אחרי ההחלפה (גרייס אמור לעבוד)
        rt.cls_pick = pick_switch
        r2 = run_once(raw_metrics=f2, library=lib, exercise_id=None, payload_version="1.0")
        _dump_core(r2, "REPORT #2 (RIGHT AFTER SWITCH)")
        _dump_canonical(r2.get("measurements") or {}, title="canonical after normalizer (R2)")
        ex2 = lib.index_by_id.get((r2.get("exercise") or {}).get("id"))
        _dump_availability(ex2, r2.get("measurements") or {}, "availability snapshot (R2)")

        # המתנה > EXR_GRACE_MS
        grace_ms = int(os.environ.get("EXR_GRACE_MS", "800"))
        time.sleep((grace_ms + 200)/1000.0)

        # REPORT #3A — אחרי הגרייס: BAD (עדיין בלי ברכיים)
        rt.cls_pick = pick_stay
        r3_bad = run_once(raw_metrics=f3_bad, library=lib, exercise_id=None, payload_version="1.0")
        _dump_core(r3_bad, "REPORT #3A (after grace — BAD: still missing knees)")
        _dump_canonical(r3_bad.get("measurements") or {}, title="canonical after normalizer (R3A)")
        ex3a = lib.index_by_id.get((r3_bad.get("exercise") or {}).get("id"))
        _dump_availability(ex3a, r3_bad.get("measurements") or {}, "availability snapshot (R3A)")

        # REPORT #3B — אחרי הגרייס: GOOD (מוסיפים ברכיים)
        r3_good = run_once(raw_metrics=f3_good, library=lib, exercise_id=None, payload_version="1.0")
        _dump_core(r3_good, "REPORT #3B (after grace — GOOD: knees provided)")
        _dump_canonical(r3_good.get("measurements") or {}, title="canonical after normalizer (R3B)")
        ex3b = lib.index_by_id.get((r3_good.get("exercise") or {}).get("id"))
        _dump_availability(ex3b, r3_good.get("measurements") or {}, "availability snapshot (R3B)")

        # פסיקות
        ok_grace = ((r2.get("scoring") or {}).get("unscored_reason") == "grace_period")
        ok_bad   = ((r3_bad.get("scoring") or {}).get("unscored_reason") == "missing_critical: depth")
        ok_good  = (
            (r3_good.get("scoring") or {}).get("unscored_reason") is None and
            (r3_good.get("scoring") or {}).get("score_pct") is not None
        )

        print("="*80)
        print("VERDICT")
        print("="*80)
        print(f"• grace triggered after switch:      {'OK' if ok_grace else 'FAIL'}")
        print(f"• after grace (BAD) missing depth:   {'OK' if ok_bad else 'FAIL'}")
        print(f"• after grace (GOOD) scored normal:  {'OK' if ok_good else 'FAIL'}")

        if ok_grace and ok_bad and ok_good:
            print("\n✓ Deep probe passed.\n")
        else:
            raise SystemExit(2)

    finally:
        rt.cls_pick = original_cls_pick

if __name__ == "__main__":
    main()
