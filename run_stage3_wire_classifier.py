# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# בדיקת Stage 3: runtime מפעיל את המסווג לפני ניקוד.
# מצפה: exercise.id == "squat.bodyweight", יש score_pct ו-grade, ואין ריצוד בבחירה.
# -----------------------------------------------------------------------------
from __future__ import annotations
from pathlib import Path
import json

from exercise_engine.registry.loader import load_library
from exercise_engine.runtime.runtime import run_once

ROOT = Path(__file__).resolve().parent
LIB_DIR = ROOT / "exercise_library"

def main() -> int:
    print("\n" + "="*80)
    print("Stage 3 — Wire classifier in runtime")
    print("="*80)

    lib = load_library(LIB_DIR)

    raw = {
        "torso_vs_vertical_deg": 12.0,
        "knee_angle_left": 145.0,
        "knee_angle_right": 150.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.12,
        "rep_time_s": 1.25,
        "view_mode": "front",
    }

    # הרצה ללא exercise_id → runtime חייב לבחור דרך המסווג
    rep = run_once(raw_metrics=raw, library=lib, exercise_id=None, payload_version="1.0", freeze_active=False)

    ex = rep.get("exercise") or {}
    ex_id = ex.get("id")
    sc = rep.get("scoring") or {}
    score_pct = sc.get("score_pct")
    grade = sc.get("grade")

    print("\n— SUMMARY —")
    print(json.dumps({
        "exercise_id": ex_id,
        "score_pct": score_pct,
        "grade": grade
    }, ensure_ascii=False, indent=2))

    ok_pick = (ex_id == "squat.bodyweight")
    ok_score = (isinstance(score_pct, int) and 0 <= score_pct <= 100 and isinstance(grade, str))
    if ok_pick and ok_score:
        print("\n✓ Stage 3 wiring passed.\n")
        return 0
    else:
        print("\n❌ Stage 3 wiring failed. בדוק runtime.runtime או classifier.\n")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
