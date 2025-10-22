# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Stage 6 — Grace Period Deep Integrity Probe
# בדיקה מפורטת שמאבחנת למה ה-Grace לא נדלק:
# - קובע EXR_GRACE_MS בסביבה (אם לא קיים)
# - מפעיל דו"ח לפני/אחרי החלפת exercise_id (כפויה דרך הפרמטר)
# - שולף מצב פנימי מתוך runtime: _last_picked_id_runtime / _last_switch_ms_runtime
# - מחשב דלתא זמנים ומדפיס פסקי דין ברורים
# -----------------------------------------------------------------------------

from __future__ import annotations
import os
import json
import time
from pathlib import Path

# ודא שאנחנו מריצים משורש BodyPlus_XPro
ROOT = Path(__file__).resolve().parent

def pj(x):
    return json.dumps(x, ensure_ascii=False, indent=2)

def main():
    # 0) קונפיג סביבתי — נגדיר Grace אם לא מוגדר
    os.environ.setdefault("EXR_GRACE_MS", "800")          # 800ms ברירת מחדל
    os.environ.setdefault("EXR_FREEZE_DURING_REP", "1")   # לא רלוונטי כאן אבל טוב שיהיה
    # (LOWCONF_GATE לא רלוונטי כאן)

    print("\n" + "="*80)
    print("Stage 6 — Grace Period Deep Integrity Probe")
    print("="*80 + "\n")

    # 1) טעינת ספרייה
    from exercise_engine.registry.loader import load_library
    lib = load_library(ROOT / "exercise_library")
    print(f"✓ ספרייה נטענה: {lib.version}\n")

    # נאסוף שני מזהי תרגיל שונים (נעדיף squat.bodyweight ולאחריו squat.base אם קיים)
    ids = list(lib.index_by_id.keys())
    bw_id = "squat.bodyweight" if "squat.bodyweight" in ids else (ids[0] if ids else None)

    # חפש id נוסף שונה מהראשון
    alt_id = None
    if bw_id:
        for _id in ids:
            if _id != bw_id:
                alt_id = _id
                break

    # אם אין חלופה — אין איך לבדוק גרייס
    if not bw_id or not alt_id:
        print("✗ אין שני תרגילים שונים בספרייה — לא ניתן לבדוק Grace switch.")
        print("ids:", ids)
        raise SystemExit(2)

    # 2) הרצת runtime — נרצה לגשת גם למשתנים פנימיים שלו
    from exercise_engine.runtime import runtime as rt

    # payload בסיסי; שים לב: חסרים ברכיים כדי שה־validate ייתן 'missing_critical: depth'
    # זה חשוב כדי לראות אם grace מחליף את הסיבה הזמנית ל'grace_period'
    base_payload = {
        "torso_vs_vertical_deg": 12.0,
        # -------- חסר בכוונה כדי לגרום ל-depth להיות unavailable --------
        # "knee_angle_left": 150.0,
        # "knee_angle_right": 152.0,
        "hip_left_deg": 100.0,
        "hip_right_deg": 102.0,
        "feet_w_over_shoulders_w": 1.10,
        "rep_time_s": 1.2,
    }

    # 3) דו"ח ראשון — בחר במפורש את ה-BW
    r1 = rt.run_once(raw_metrics=dict(base_payload), library=lib,
                     exercise_id=bw_id, payload_version="1.0")

    # שליפת מצב פנימי מהרנטיים (אחרי הקריאה הראשונה)
    rt_runtime_sw_ms_1 = getattr(rt, "_last_switch_ms_runtime", None)
    rt_runtime_last_id_1 = getattr(rt, "_last_picked_id_runtime", None)
    cls_state = getattr(rt, "_classifier_state", None)
    cls_last_sw_1 = getattr(getattr(cls_state, "last_switch_ms", None), "__int__", lambda: None)()

    print("\n" + "="*80)
    print("REPORT #1 (before switch)")
    print("="*80)
    print(pj({
        "exercise_id": r1.get("exercise", {}).get("id"),
        "unscored_reason": r1.get("scoring", {}).get("unscored_reason"),
        "score_pct": r1.get("scoring", {}).get("score_pct"),
        "runtime_last_switch_ms": rt_runtime_sw_ms_1,
        "classifier_last_switch_ms": cls_last_sw_1,
    }))

    # 4) המתנה קצרה כדי לייצר דלתא־זמן ברורה
    time.sleep(0.12)  # 120ms

    # 5) דו"ח שני — כופים החלפת תרגיל (alt_id), ומיד בודקים אם grace נדלק
    r2 = rt.run_once(raw_metrics=dict(base_payload), library=lib,
                     exercise_id=alt_id, payload_version="1.0")

    # שליפת מצב פנימי אחרי ההחלפה
    rt_runtime_sw_ms_2 = getattr(rt, "_last_switch_ms_runtime", None)
    rt_runtime_last_id_2 = getattr(rt, "_last_picked_id_runtime", None)
    cls_last_sw_2 = getattr(getattr(cls_state, "last_switch_ms", None), "__int__", lambda: None)()

    now_ms = int(time.time() * 1000)
    delta_runtime = (now_ms - rt_runtime_sw_ms_2) if rt_runtime_sw_ms_2 else None
    delta_classifier = (now_ms - cls_last_sw_2) if cls_last_sw_2 else None

    print("\n" + "="*80)
    print("REPORT #2 (RIGHT AFTER FORCED SWITCH)")
    print("="*80)
    print(pj({
        "exercise_id": r2.get("exercise", {}).get("id"),
        "unscored_reason": r2.get("scoring", {}).get("unscored_reason"),
        "score_pct": r2.get("scoring", {}).get("score_pct"),
        "grade": r2.get("scoring", {}).get("grade"),
        "runtime_last_switch_ms": rt_runtime_sw_ms_2,
        "classifier_last_switch_ms": cls_last_sw_2,
    }))

    # 6) פרטי סביבה/מצב
    print("\n" + "="*80)
    print("ENV / STATE")
    print("="*80)
    print(pj({
        "EXR_GRACE_MS": int(os.environ.get("EXR_GRACE_MS", "0")),
        "picked_ids": {
            "before": rt_runtime_last_id_1,
            "after":  rt_runtime_last_id_2,
        },
        "runtime_last_switch_ms": rt_runtime_sw_ms_2,
        "classifier_last_switch_ms": cls_last_sw_2,
        "delta_runtime_ms": delta_runtime,
        "delta_classifier_ms": delta_classifier,
        "library_ids_sample": ids[:5],
        "forced_ids": {"first": bw_id, "second": alt_id},
    }))

    # 7) פסק דין
    print("\n" + "="*80)
    print("VERDICT")
    print("="*80)
    expected_reason = "grace_period"
    got_reason = r2.get("scoring", {}).get("unscored_reason")

    ok_switch_tracked = (rt_runtime_sw_ms_2 is not None) or (cls_last_sw_2 is not None)
    print(f"• switch tracked? {'OK' if ok_switch_tracked else 'FAIL'}")

    if got_reason == expected_reason:
        print("• grace triggered right-after-switch: OK")
        exit_code = 0
    else:
        print(f"• grace triggered right-after-switch: FAIL (got '{got_reason}', expected '{expected_reason}')")
        # עזר לאבחון: מי לא זז?
        if rt_runtime_sw_ms_2 is None and cls_last_sw_2 is None:
            print("  Hint: לא התגלה זמן החלפה (לא ע״י runtime ולא ע״י classifier).")
            print("        ודא שהקריאה השנייה באמת שינתה exercise_id (כרגע: ", r2.get('exercise', {}).get('id'), ")")
        elif rt_runtime_sw_ms_2 is not None:
            print(f"  Runtime switch detected {delta_runtime}ms ago → כנראה חלון ה-Grace קצר מדי או הבדיקה איטית.")
            print("  נסה להעלות EXR_GRACE_MS ל-1500 ולהריץ שוב.")
        else:
            print("  Classifier state החזיר last_switch_ms, אבל runtime לא זיהה — בדוק שדריסת exercise_id לא עוקפת את המסווג אצלך.")
        exit_code = 2

    print("\n✓ הבדיקה הסתיימה.\n")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
