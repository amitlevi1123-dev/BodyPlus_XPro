# -*- coding: utf-8 -*-
# Stage 10 — Strong Switch Override end-to-end test
import os, time, json
from pathlib import Path

from exercise_engine.registry.loader import load_library
from exercise_engine.runtime.runtime import run_once

ROOT = Path(__file__).resolve().parent
LIB = load_library(ROOT / "exercise_library")

def print_block(title, obj):
    print("\n" + "="*80)
    print(title)
    print("="*80)
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main():
    # הבטחת ENV לחלק A
    os.environ["EXR_STRONG_SWITCH"] = "1"
    os.environ["EXR_STRONG_SWITCH_MARGIN"] = "0.45"
    os.environ["EXR_STRONG_SWITCH_BYPASS_FREEZE"] = "1"
    os.environ["EXR_GRACE_MS"] = "800"
    os.environ.pop("EXR_STRONG_SWITCH_BYPASS_GRACE", None)  # ברירת מחדל: לא לעקוף גרייס

    print("\n" + "="*80)
    print("Stage 10 — Strong Switch Override")
    print("="*80)
    print(f"✓ ספרייה נטענה: {LIB.version}")

    # Frame 1: מתחילים עם squat.bodyweight, בתוך חלון חזרה (freeze)
    f1 = {
        "torso_vs_vertical_deg": 12.0,
        "knee_angle_left": 145.0,
        "knee_angle_right": 151.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.15,
        "rep_time_s": 1.3,
        "rep.in_rep_window": True,    # Freeze active
    }
    r1 = run_once(raw_metrics=f1, library=LIB, exercise_id=None, payload_version="1.0")
    print_block("REPORT #1 (baseline, inside freeze)", {
        "exercise_id": r1.get("exercise",{}).get("id"),
        "unscored_reason": r1.get("scoring",{}).get("unscored_reason"),
        "score_pct": r1.get("scoring",{}).get("score_pct"),
    })

    # Frame 2: מגיע "תרגיל חדש" עם פער ענק (נדמה "ex.other" – בפועל נגרום למסווג לבחור ב-squat.base)
    # כדי ליצור פער ענק: נוריד את המאפיינים שמשרתים את BW, ונוסיף כאלה שמשרתים את "האופציה השניה".
    # אצלנו אין Lunge אמיתי בספרייה, אז נכריח שינוי בנתונים כדי שהמסווג יעדיף squat.base.
    f2 = {
        "torso_vs_vertical_deg": 8.0,    # מיישר, כדי לשנות ציוני התאמה
        "hip_left_deg": 95.0,
        "hip_right_deg": 96.0,
        # לא נשים ברכיים כדי לא לקבל ניקוד עומק גבוה ל-BW
        "features.stance_width_ratio": 1.05,
        "rep_time_s": 1.1,
        "rep.in_rep_window": True,       # עדיין בתוך freeze
    }
    r2 = run_once(raw_metrics=f2, library=LIB, exercise_id=None, payload_version="1.0")
    print_block("REPORT #2 (RIGHT AFTER STRONG OVERRIDE, inside freeze)", {
        "exercise_id": r2.get("exercise",{}).get("id"),
        "unscored_reason": r2.get("scoring",{}).get("unscored_reason"),
        "score_pct": r2.get("scoring",{}).get("score_pct"),
    })

    # ציפייה A: למרות שהיינו ב-freeze, אם היה פער ענק → ההחלפה התבצעה (id השתנה)
    # אבל בגלל שאין BYPASS_GRACE, נקבל grace_period.

    verdict_A = []
    ex2 = r2.get("exercise",{}).get("id")
    if ex2 and ex2 != r1.get("exercise",{}).get("id"):
        verdict_A.append("• switched despite freeze: OK")
    else:
        verdict_A.append("• switched despite freeze: FAIL")
    if r2.get("scoring",{}).get("unscored_reason") == "grace_period":
        verdict_A.append("• grace after strong switch: OK")
    else:
        verdict_A.append("• grace after strong switch: FAIL")

    print("\n" + "="*80)
    print("VERDICT — Scenario A (no bypass grace)")
    print("="*80)
    for v in verdict_A:
        print(v)

    # Scenario B: לעקוף Grace — ציון מיידי לתרגיל החדש
    os.environ["EXR_STRONG_SWITCH_BYPASS_GRACE"] = "1"

    # Frame 3: עוד פריים המשך, עדיין "מצב חדש"
    f3 = {
        "torso_vs_vertical_deg": 8.0,
        "hip_left_deg": 95.0,
        "hip_right_deg": 96.0,
        "features.stance_width_ratio": 1.05,
        "rep_time_s": 1.1,
        "rep.in_rep_window": True,   # עדיין בתוך חזרה
        # נוסיף גם ברכיים כדי לאפשר ניקוד מלא:
        "knee_angle_left": 140.0,
        "knee_angle_right": 148.0,
    }
    r3 = run_once(raw_metrics=f3, library=LIB, exercise_id=None, payload_version="1.0")
    print_block("REPORT #3 (bypass grace → immediate scoring if available)", {
        "exercise_id": r3.get("exercise",{}).get("id"),
        "unscored_reason": r3.get("scoring",{}).get("unscored_reason"),
        "score_pct": r3.get("scoring",{}).get("score_pct"),
        "grade": r3.get("scoring",{}).get("grade"),
    })

    verdict_B = []
    if r3.get("scoring",{}).get("unscored_reason") is None and isinstance(r3.get("scoring",{}).get("score_pct"), int):
        verdict_B.append("• bypassed grace (scored immediately): OK")
    else:
        verdict_B.append("• bypassed grace (scored immediately): FAIL")

    print("\n" + "="*80)
    print("VERDICT — Scenario B (bypass grace)")
    print("="*80)
    for v in verdict_B:
        print(v)

if __name__ == "__main__":
    main()
