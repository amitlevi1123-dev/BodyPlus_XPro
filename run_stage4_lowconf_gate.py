# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Stage 4: Low-Confidence Gate (אופציונלי).
# מפעילים ENV → שולחים pose.confidence נמוך → מצפים ל-unscored_reason="low_pose_confidence".
# -----------------------------------------------------------------------------
from __future__ import annotations
from pathlib import Path
import os
import json

from exercise_engine.registry.loader import load_library
from exercise_engine.runtime.runtime import run_once

ROOT = Path(__file__).resolve().parent
LIB_DIR = ROOT / "exercise_library"

def main() -> int:
    print("\n" + "="*80)
    print("Stage 4 — Low-Confidence Gate (ENV-controlled)")
    print("="*80)

    # ודא שה-Gate מופעל
    gate = os.getenv("EXR_LOWCONF_GATE", "0")
    print(f"EXR_LOWCONF_GATE={gate} (set to 1 to enable)")

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
        "pose.confidence": 0.25,  # נמוך מהברירת-מחדל 0.4 → אמור לחסום אם gate פעיל
    }

    rep = run_once(raw_metrics=raw, library=lib, exercise_id=None, payload_version="1.0", freeze_active=False)

    print("\n— SUMMARY —")
    print(json.dumps({
        "exercise_id": (rep.get("exercise") or {}).get("id"),
        "score_pct": (rep.get("scoring") or {}).get("score_pct"),
        "unscored_reason": (rep.get("scoring") or {}).get("unscored_reason"),
    }, ensure_ascii=False, indent=2))

    reason = (rep.get("scoring") or {}).get("unscored_reason")
    gate_on = os.getenv("EXR_LOWCONF_GATE", "0") == "1"

    if gate_on and reason == "low_pose_confidence":
        print("\n✓ Gate worked: report is unscored due to low pose confidence.\n")
        return 0
    elif not gate_on and reason is None:
        print("\n✓ Gate is OFF (as expected): report scored normally.\n")
        return 0
    else:
        print("\n❌ Unexpected result. Check ENV and runtime.\n")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
