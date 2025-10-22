# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Stage 5 — Freeze Guard Test
# בדיקה חיה למסווג: כשה-Freeeze פעיל באמצע חזרה, גם אם מועמד אחר עדיף — נשארים על הקודם.
# הבדיקה בונה ספרייה "מוקטנת" עם שני תרגילים: squat.bodyweight (BW) ו-ex.other.
# נסמן freeze על פריימים 6-8; בקטעים אלו נראה שהבחירה לא מתחלפת.
# בסיום החלון, מתבצעת החלפה אחת (במכוון) כדי להוכיח שההגנה לא חוסמת לנצח.
# -----------------------------------------------------------------------------

from __future__ import annotations
import os, json, time
from typing import Any, Dict, List

from exercise_engine.classifier.classifier import pick, ClassifierState, Candidate

# נכבה Low-Confidence Gate לבדיקה הזו
os.environ["EXR_LOWCONF_GATE"] = "0"
# נדליק Freeze בזמן חזרה (ברירת מחדל 1, אבל נבטיח)
os.environ["EXR_FREEZE_DURING_REP"] = "1"

# ===== ספריית אימות מזערית לשני תרגילים =====

class _FakeExercise:
    def __init__(self, id_: str, equipment: str, must_have: List[str]) -> None:
        self.id = id_
        self.family = "squat"
        self.equipment = equipment  # "none" → Bodyweight
        self.display_name = id_
        self.meta = {"family": "squat", "equipment": equipment, "match_hints": {"must_have": must_have}}
        self.match_hints = {"must_have": must_have}
        self.criteria = {}
        self.thresholds = {}
        self.weights = {}

class _MiniLib:
    def __init__(self, exs: List[_FakeExercise]) -> None:
        self.exercises = exs
        self.index_by_id = {e.id: e for e in exs}
        self.aliases = {}  # לא נחוץ פה

def _frame(canon_keys: Dict[str, Any], *, freeze: bool = False) -> Dict[str, Any]:
    d = dict(canon_keys)
    if freeze:
        d["rep.in_rep_window"] = True
        d["rep.phase"] = "down"
    return d

def main() -> None:
    # נגדיר שני "תרגילים": BW דורש torso_forward_deg, OTHER דורש phantom_key
    ex_bw = _FakeExercise("squat.bodyweight", "none", ["torso_forward_deg"])
    ex_other = _FakeExercise("ex.other", "none", ["phantom_key"])
    lib = _MiniLib([ex_bw, ex_other])

    state = ClassifierState()

    # נבנה רצף פריימים:
    # 1-5: יש רק torso_forward_deg → BW מנצח
    # 6-8: נעלים torso_forward_deg ונכניס phantom_key *וגם* freeze=True → אמור להישאר BW
    # 9-10: נשחרר freeze ונשאיר phantom_key → אמורה להיות החלפה חד-פעמית ל-ex.other
    seq: List[Dict[str, Any]] = []
    for _ in range(5):
        seq.append(_frame({"torso_forward_deg": 12.0}, freeze=False))
    for _ in range(3):
        seq.append(_frame({"phantom_key": 1.0}, freeze=True))
    for _ in range(2):
        seq.append(_frame({"phantom_key": 1.0}, freeze=False))

    picks: List[str] = []
    switches = 0
    prev = None

    for i, canon in enumerate(seq, start=1):
        res = pick(canon, lib, prev_state=state, freeze_active=bool(canon.get("rep.in_rep_window")))
        picks.append(res.exercise_id or "none")
        if prev and res.exercise_id and res.exercise_id != prev:
            switches += 1
        prev = res.exercise_id
        time.sleep(0.01)  # סימולציה קלה

    unique = list(dict.fromkeys(picks))

    print("\n================================================================================")
    print("Stage 5 — Freeze Guard (Classifier Unit Test)")
    print("================================================================================")
    print(f"• picks per frame: {picks}")
    print(f"• unique picks:    {unique}")
    print(f"• switches:        {switches}")

    # ציפיות:
    # - פריימים 1..8 אמורים להישאר BW (ב-6..8 יש Freeze)
    # - אחרי סיום freeze תהיה החלפה חד-פעמית ל-ex.other
    ok_prefix = all(p == "squat.bodyweight" for p in picks[:8])
    ok_switch_once = (switches == 1 and picks[-1] == "ex.other")

    print("\n— Verdict —")
    print(f"✓ stayed on BW during freeze: {'OK' if ok_prefix else 'FAIL'}")
    print(f"✓ switched once after freeze: {'OK' if ok_switch_once else 'FAIL'}")

    if ok_prefix and ok_switch_once:
        print("\n✓ Stage 5 freeze-guard passed.")
    else:
        raise SystemExit(2)

if __name__ == "__main__":
    main()
