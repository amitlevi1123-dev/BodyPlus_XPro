# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# run_full_smoketest.py
# הסבר קצר (עברית):
# בדיקת עשן מקצה לקצה למנוע התרגילים:
# 1) טוען את ספריית התרגילים (YAML) + aliases.
# 2) מריץ את המסווג+המנוע על 3 תרחישים:
#    A. GOOD – פיילוד תקין (ציון כללי אמור להיות קיים, 0..100).
#    B. MISSING KNEES – חסר מדידות ברך → אמור להיות Unscored עם סיבה missing_critical: depth.
#    C. SHALLOW DEPTH – עומק חלש → ציון קיים אך נמוך יותר, ולפחות רמז אחד לשיפור.
# 3) מדפיס תקצירים, טיפים (hints) ותמצית אינדיקציות.
#
# הערות:
# - הבדיקה לא משנה קבצים קיימים ולא תלויה ב-core. היא עובדת על מדידות קנוניות (dict).
# - אם אחת הבדיקות נכשלת, הסקריפט יחזיר קוד יציאה 2.
# -----------------------------------------------------------------------------

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Any, List

# ייבואי המנוע/ספרייה
try:
    from exercise_engine.registry.loader import load_library
    from exercise_engine.runtime.runtime import run_once
except Exception as e:
    print("❌ לא הצלחתי לייבא את המנוע/הטוען. ודא שמבנה הפרויקט תקין.")
    print(f"Details: {e}")
    sys.exit(2)

ROOT = Path(__file__).resolve().parent
LIB_DIR = ROOT / "exercise_library"

# ---------- עזרי הדפסה ----------

def hr(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

def show_summary(label: str, report: Dict[str, Any]) -> None:
    print(f"\n— {label} —")
    exer = report.get("exercise") or {}
    scoring = report.get("scoring") or {}
    coverage = report.get("coverage") or {}
    summary = {
        "exercise": {
            "id": exer.get("id"),
            "family": exer.get("family"),
            "equipment": exer.get("equipment"),
            "display_name": exer.get("display_name"),
        },
        "score_pct": scoring.get("score_pct"),
        "grade": scoring.get("grade"),
        "unscored_reason": scoring.get("unscored_reason"),
        "coverage": {
            "available_pct": coverage.get("available_pct"),
            "available_count": coverage.get("available_count"),
            "total_criteria": coverage.get("total_criteria"),
            "missing_reasons_top": coverage.get("missing_reasons_top", []),
        },
        "hints_count": len(report.get("hints", [])),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

def show_criteria(report: Dict[str, Any]) -> None:
    scoring = report.get("scoring") or {}
    items: List[Dict[str, Any]] = scoring.get("criteria") or []
    if not items:
        print("Per-criterion: (אין פריטים)")
        return
    print("\nPer-criterion:")
    for it in items:
        cid = it.get("id")
        avail = it.get("available")
        spct = it.get("score_pct")
        reason = it.get("reason")
        if spct is None and isinstance(it.get("score"), (int, float)):
            # אם יש score אך לא הוזרם score_pct
            try:
                spct = int(round(float(it.get("score")) * 100.0))
            except Exception:
                spct = None
        print(f"  • {cid:<12} available={str(avail):<5} score_pct={spct if spct is not None else 'None':>4} reason={reason or 'None'}")

def show_hints(report: Dict[str, Any]) -> None:
    hints = report.get("hints", [])
    print("\nHints:")
    if not hints:
        print("  (אין)")
        return
    for h in hints:
        print(f"  - {h}")

def show_diagnostics_tail(report: Dict[str, Any], tail: int = 5) -> None:
    diags = report.get("diagnostics", [])
    print("\nDiagnostics (tail):")
    if not diags:
        print("  (אין)")
        return
    for ev in diags[-tail:]:
        sev = ev.get("severity", "info")
        typ = ev.get("type", "event")
        msg = ev.get("message", "")
        print(f"  - [{sev}] {typ} :: {msg}")

# ---------- בדיקות ----------

def assert_between_0_100(x: Any, label: str) -> None:
    if not isinstance(x, int):
        raise AssertionError(f"{label}: לא שלם (int). ערך: {x}")
    if x < 0 or x > 100:
        raise AssertionError(f"{label}: מחוץ לטווח 0..100. ערך: {x}")

def main() -> int:
    failures: List[str] = []

    # 1) טעינת הספרייה
    hr("טעינת ספריית תרגילים")
    try:
        lib = load_library(LIB_DIR)
        print(f"✓ נטענה ספרייה: {LIB_DIR} (גרסה: {lib.version})")
        # נוודא שיש את הווריאנט bodyweight לסקוואט
        ids = [getattr(ex, "id", None) for ex in lib.exercises]
        if "squat.bodyweight" not in ids:
            failures.append("לא נמצא תרגיל squat.bodyweight בספרייה.")
    except Exception as e:
        print("❌ כשל בטעינת הספרייה:", e)
        return 2

    # 2) CASE A — GOOD
    hr("CASE A — GOOD (פיילוד טוב, אמור לקבל ציון)")
    raw_good = {
        "torso_vs_vertical_deg": 12.0,   # posture
        "knee_angle_left": 145.0,        # depth
        "knee_angle_right": 150.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.10, # stance_width
        "rep_time_s": 1.2,               # tempo
    }
    try:
        rep_good = run_once(raw_metrics=raw_good, library=lib, exercise_id="squat.bodyweight", payload_version="1.0")
        show_summary("SUMMARY (GOOD)", rep_good)
        show_criteria(rep_good)
        show_hints(rep_good)
        show_diagnostics_tail(rep_good)

        # אימותים בסיסיים
        sc = (rep_good.get("scoring") or {})
        spct = sc.get("score_pct")
        if spct is None:
            failures.append("GOOD: score_pct לא קיים.")
        else:
            try:
                assert_between_0_100(spct, "GOOD.score_pct")
            except AssertionError as e:
                failures.append(str(e))
        if sc.get("unscored_reason") is not None:
            failures.append("GOOD: לא אמורה להיות סיבת Unscored.")
    except Exception as e:
        failures.append(f"GOOD: חריג במהלך הרצה: {e}")

    # 3) CASE B — MISSING KNEES (חסר קריטי לעומק)
    hr("CASE B — MISSING KNEES (depth unavailable → Unscored)")
    raw_missing = {
        "torso_vs_vertical_deg": 14.0,     # posture זמין
        # ברכיים חסרות → depth לא זמין
        "hip_left_deg": 100.0,
        "hip_right_deg": 103.0,
        "feet_w_over_shoulders_w": 1.05,   # stance_width
        "rep_time_s": 1.5,                 # tempo
    }
    try:
        rep_missing = run_once(raw_metrics=raw_missing, library=lib, exercise_id="squat.bodyweight", payload_version="1.0")
        show_summary("SUMMARY (MISSING KNEES)", rep_missing)
        show_criteria(rep_missing)
        show_hints(rep_missing)
        show_diagnostics_tail(rep_missing)

        sc = (rep_missing.get("scoring") or {})
        if sc.get("score_pct") is not None:
            failures.append("MISSING: score_pct אמור להיות None (Unscored).")
        reason = sc.get("unscored_reason")
        if not reason or "depth" not in str(reason):
            failures.append(f"MISSING: unscored_reason אמור לציין depth. קיבלנו: {reason}")
    except Exception as e:
        failures.append(f"MISSING: חריג במהלך הרצה: {e}")

    # 4) CASE C — SHALLOW DEPTH (עומק חלש → ציון נמוך יותר)
    hr("CASE C — SHALLOW DEPTH (עומק חלש → ציון קיים + רמז לשיפור)")
    raw_shallow = {
        "torso_vs_vertical_deg": 12.0,     # posture OK
        "knee_angle_left": 150.0,          # עומק חלש (גדול → לא עמוק)
        "knee_angle_right": 152.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 103.0,
        "feet_w_over_shoulders_w": 1.12,   # stance OK
        "rep_time_s": 1.1,                 # tempo OK
    }
    try:
        rep_shallow = run_once(raw_metrics=raw_shallow, library=lib, exercise_id="squat.bodyweight", payload_version="1.0")
        show_summary("SUMMARY (SHALLOW DEPTH)", rep_shallow)
        show_criteria(rep_shallow)
        show_hints(rep_shallow)
        show_diagnostics_tail(rep_shallow)

        sc = (rep_shallow.get("scoring") or {})
        spct = sc.get("score_pct")
        if spct is None:
            failures.append("SHALLOW: score_pct אמור להיות קיים (גם אם נמוך).")
        else:
            try:
                assert_between_0_100(spct, "SHALLOW.score_pct")
            except AssertionError as e:
                failures.append(str(e))
        hints = rep_shallow.get("hints", [])
        if not any("העמק מעט את הסקוואט" in h for h in hints):
            failures.append("SHALLOW: מצופה לקבל רמז שקשור לעומק (העמק מעט את הסקוואט).")
    except Exception as e:
        failures.append(f"SHALLOW: חריג במהלך הרצה: {e}")

    # סיכום
    hr("סיכום")
    if failures:
        print("❌ נמצאו כשלים:")
        for f in failures:
            print(" -", f)
        return 2
    print("✓ כל בדיקות העשן עברו בהצלחה.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
