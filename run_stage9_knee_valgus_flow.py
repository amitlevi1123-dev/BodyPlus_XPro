# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Stage 9 — Knee Valgus Flow (available → scored → hints)
#
# מה בודקים?
#   A) בלי נתוני knee_foot_alignment_* → הקריטריון לא זמין + hint חסר.
#   B) עם נתונים קטנים (טוב) → score גבוה + hint חיובי.
#   C) עם נתונים גדולים (חלש) → score נמוך + hint לשיפור.
# -----------------------------------------------------------------------------

from __future__ import annotations
import json
from pathlib import Path
from exercise_engine.registry.loader import load_library
from exercise_engine.runtime.runtime import run_once

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "exercise_library"

def pretty(x): return json.dumps(x, ensure_ascii=False, indent=2)

def base_payload():
    return {
        "torso_vs_vertical_deg": 12.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.15,
        "rep_time_s": 1.3,
        # שים לב: אין פה ברכיים לעומק—אנחנו לא בודקים עומק עכשיו, רק Knee Valgus
        "knee_angle_left": 120.0,
        "knee_angle_right": 120.0,
    }

def extract_knee_valgus(report):
    crits = (report.get("scoring") or {}).get("criteria") or []
    kv = [c for c in crits if c.get("id") == "knee_valgus"]
    return kv[0] if kv else {}

def main():
    print("\n" + "="*80)
    print("Stage 9 — Knee Valgus Flow")
    print("="*80 + "\n")

    lib = load_library(LIB)
    print(f"✓ ספרייה נטענה: {lib.version}\n")

    # A) אין נתונים → unavailable
    fA = base_payload()
    rA = run_once(raw_metrics=fA, library=lib, payload_version="1.0", exercise_id="squat.bodyweight")
    kvA = extract_knee_valgus(rA)
    print("CASE A (no alignment data)")
    print(pretty({
        "available": kvA.get("available"),
        "score_pct": kvA.get("score_pct"),
        "reason": kvA.get("reason"),
        "hints": rA.get("hints")[:2],
    }), "\n")

    # B) נתונים קטנים (3°/4°) → טוב
    fB = base_payload()
    fB.update({
        "knee_foot_alignment_left_deg": 3.0,
        "knee_foot_alignment_right_deg": 4.0,
    })
    rB = run_once(raw_metrics=fB, library=lib, payload_version="1.0", exercise_id="squat.bodyweight")
    kvB = extract_knee_valgus(rB)
    print("CASE B (good: 3°/4°)")
    print(pretty({
        "available": kvB.get("available"),
        "score_pct": kvB.get("score_pct"),
        "reason": kvB.get("reason"),
        "first_hint": (rB.get("hints") or [None])[0],
    }), "\n")

    # C) נתונים גדולים (12°/15°) → חלש
    fC = base_payload()
    fC.update({
        "knee_foot_alignment_left_deg": 12.0,
        "knee_foot_alignment_right_deg": 15.0,
    })
    rC = run_once(raw_metrics=fC, library=lib, payload_version="1.0", exercise_id="squat.bodyweight")
    kvC = extract_knee_valgus(rC)
    print("CASE C (weak: 12°/15°)")
    print(pretty({
        "available": kvC.get("available"),
        "score_pct": kvC.get("score_pct"),
        "reason": kvC.get("reason"),
        "first_hint": (rC.get("hints") or [None])[0],
    }), "\n")

    # פסיקות קצרות
    okA = (kvA.get("available") is False)
    okB = (kvB.get("available") is True and (kvB.get("score_pct") or 0) >= 85)
    okC = (kvC.get("available") is True and (kvC.get("score_pct") or 100) <= 60)

    print("="*80)
    print("VERDICT")
    print("="*80)
    print(f"• A unavailable without data: {'OK' if okA else 'FAIL'}")
    print(f"• B good values scored high:  {'OK' if okB else 'FAIL'}")
    print(f"• C weak values scored low:   {'OK' if okC else 'FAIL'}")

    if okA and okB and okC:
        print("\n✓ Stage 9 passed.\n")
    else:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
