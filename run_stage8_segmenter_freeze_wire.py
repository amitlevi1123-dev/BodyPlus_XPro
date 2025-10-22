# -*- coding: utf-8 -*-
"""
Stage 8 — Segmenter Freeze Wiring (Final fix, survives normalizer)
מה בודקים?
1) בזמן freeze אסור להחליף תרגיל (נשארים על הקודם).
2) כשה-freeze יורד ומגיע אות החלפה — חייבים לעבור לתרגיל אחר קיים.

תיקון חשוב:
- משתמשים ב־rep.simulate_switch (עובר את הנורמליזציה), לא __simulate_switch__ שנזרק.
- המונקיפאץ' מכבד freeze_active: בזמן freeze שומר תרגיל קודם; אחרי freeze מבצע מעבר ומעדכן last_switch_ms.
"""

import json
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from pathlib import Path
from copy import deepcopy

from exercise_engine.registry.loader import load_library
from exercise_engine.runtime.runtime import run_once

# נשתמש במודולים כדי למונקיפאץ' גם את המקור וגם את הסימבול ב-runtime:
import exercise_engine.classifier.classifier as cls_mod
import exercise_engine.runtime.runtime as rt_mod
from exercise_engine.classifier.classifier import ClassifierState

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "exercise_library"

# ---- דמה מדידות ----
CANON_BASE = {
    "torso_vs_vertical_deg": 12.0,
    "hip_left_deg": 100.0,
    "hip_right_deg": 102.0,
    "feet_w_over_shoulders_w": 1.15,
    "rep_time_s": 1.3,
    # בלי knees כדי ש-depth לא יהיה זמין (לא קריטי למבחן ההחלפה)
}

def _norm_payload(d: dict) -> dict:
    return dict(d)

# ---- מונקיפאץ' למסווג: כבד freeze, מחליף רק כשהוא כבוי, משתמש ב-last_switch_ms ----
def make_patched_pick(target_after_id: str):
    @dataclass
    class Candidate:
        id: str
        score: float

    @dataclass
    class Stability:
        kept_previous: bool = False
        margin: float = 0.0
        freeze_active: bool = False
        last_switch_ms: int | None = None

    @dataclass
    class PickResult:
        status: str
        exercise_id: str | None
        family: str | None
        equipment_inferred: str
        confidence: float
        reason: str
        stability: Stability
        candidates: list[Candidate] = field(default_factory=list)
        state: ClassifierState = field(default_factory=ClassifierState)
        diagnostics: list[dict] = field(default_factory=list)

    # state משותף בין קריאות (כמו ב-runtime)
    _state = ClassifierState()

    def _pick(canonical, library, prev_state=None, freeze_active=False, **kwargs):
        state = prev_state or _state
        simulate_switch = bool(canonical.get("rep.simulate_switch"))

        prev_id = state.prev_exercise_id
        chosen = prev_id or "squat.bodyweight"

        # אם ביקשו "להחליף" אבל יש FREEZE — נשארים על הקודם
        if simulate_switch and freeze_active and prev_id:
            chosen = prev_id
            kept_previous = True
            last_sw = state.last_switch_ms  # אין החלפה חדשה
            diag = {"type":"patched_pick_used","note":"kept due to freeze","simulate_switch":True,"freeze":True,"chosen":chosen}
        elif simulate_switch and not freeze_active:
            # מעבר אמיתי ליעד
            chosen = target_after_id
            kept_previous = False
            last_sw = int(time.time() * 1000)
            state.last_switch_ms = last_sw
            diag = {"type":"patched_pick_used","note":"switched after freeze","simulate_switch":True,"freeze":False,"chosen":chosen,"last_switch_ms":last_sw}
        else:
            # ללא בקשת החלפה — שמור/בחר BW
            if not prev_id:
                chosen = "squat.bodyweight"
            kept_previous = False
            last_sw = state.last_switch_ms
            diag = {"type":"patched_pick_used","note":"no switch request","simulate_switch":False,"freeze":bool(freeze_active),"chosen":chosen}

        # עדכון prev
        state.prev_exercise_id = chosen

        pr = PickResult(
            status="ok",
            exercise_id=chosen,
            family=None,
            equipment_inferred="none",
            confidence=1.0,
            reason="monkeypatch",
            stability=Stability(
                kept_previous=kept_previous,
                margin=1.0,
                freeze_active=freeze_active,
                last_switch_ms=last_sw
            ),
            candidates=[Candidate(id=chosen, score=1.0)],
            state=state,
            diagnostics=[diag]
        )
        return pr

    return _pick


def main():
    print("\n" + "="*80)
    print("Stage 8 — Segmenter Freeze Wiring")
    print("="*80 + "\n")

    lib = load_library(LIB)
    print(f"✓ ספרייה נטענה: {lib.version}\n")

    # שומרים מקורי
    original_pick_mod = cls_mod.pick
    original_pick_rt  = rt_mod.cls_pick

    try:
        patched = make_patched_pick("squat.base")

        # חשוב: מחליפים גם במודול המסווג וגם בסימבול שה-runtime משתמש בו!
        cls_mod.pick = patched
        rt_mod.cls_pick = patched

        # אימות שהפאצ' באמת בשימוש:
        print("Sanity: patched == cls_mod.pick ? ", patched is cls_mod.pick)
        print("Sanity: patched == rt_mod.cls_pick ?", patched is rt_mod.cls_pick, "\n")

        # REPORT #1 — לפני freeze, בלי switch → חייב להיות BW
        f1 = _norm_payload(deepcopy(CANON_BASE))
        r1 = run_once(raw_metrics=f1, library=lib, exercise_id=None, payload_version="1.0")
        picked1 = (r1.get("exercise") or {}).get("id")
        print(f"REPORT #1: {{\n  \"picked\": \"{picked1}\"\n}}")

        # REPORT #2 — freeze פעיל + בקשת switch (rep.simulate_switch=True) → לא מחליפים (נשארים BW)
        f2 = _norm_payload(deepcopy(CANON_BASE))
        f2["rep.freeze_active"] = True
        f2["rep.simulate_switch"] = True   # <<<< מפתח שעובר normalizer
        r2 = run_once(raw_metrics=f2, library=lib, exercise_id=None, payload_version="1.0")
        picked2 = (r2.get("exercise") or {}).get("id")
        print(f"REPORT #2: {{\n  \"picked\": \"{picked2}\",\n  \"freeze\": true\n}}")

        # REPORT #3 — אין freeze + בקשת switch → חייבים לעבור ל-base
        f3 = _norm_payload(deepcopy(CANON_BASE))
        f3["rep.freeze_active"] = False
        f3["rep.simulate_switch"] = True   # <<<< נשמר
        r3 = run_once(raw_metrics=f3, library=lib, exercise_id=None, payload_version="1.0")
        picked3 = (r3.get("exercise") or {}).get("id")
        print(f"REPORT #3: {{\n  \"picked\": \"{picked3}\",\n  \"freeze\": false\n}}\n")

        # פסיקות
        print("="*80)
        print("VERDICT")
        print("="*80)
        ok_blocked = (picked1 == "squat.bodyweight") and (picked2 == "squat.bodyweight")
        ok_after   = (picked3 == "squat.base")

        print(f"• blocked switch during freeze: {'OK' if ok_blocked else 'FAIL'}")
        print(f"• allowed switch after freeze:   {'OK' if ok_after else 'FAIL'}")

        if not (ok_blocked and ok_after):
            raise SystemExit(2)

    finally:
        # מחזירים את המקוריים
        cls_mod.pick = original_pick_mod
        rt_mod.cls_pick = original_pick_rt


if __name__ == "__main__":
    main()
