# tools/tests/test_squat_bodyweight_detect_and_score.py
# pytest -q

import math
import yaml
from pathlib import Path

# --- נתיבים כפי שביקשת (Windows) ---
BASE = Path(r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro\exercise_library\exercises\_base\squat.base.yaml")
BW   = Path(r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro\exercise_library\exercises\packs\bodyweight\squat\squat_bodyweight.yaml")

def load_yaml(p: Path):
    assert p.exists(), f"Missing file: {p}"
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# ---------- Helpers (מימוש מינימלי כדי לאמת את ההיגיון מה-YAML) ----------

def matches_hints(hints: dict, measurements: dict) -> bool:
    """בדיקת match_hints בסיסית בהתאם ל-YAML."""
    # must_have flags
    for k in hints.get("must_have", []):
        if not _truthy(measurements.get(k)):
            return False
    # must_not_have flags
    for k in hints.get("must_not_have", []):
        if _truthy(measurements.get(k)):
            return False
    # לא בודק pose_view/motion_pattern בפועל (דורש מודל), רק קיום מפתחות
    return True

def _truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip() != ""
    return True

def eval_threshold_window(value, target_max=None, cutoff_max=None, target_min=None, cutoff_min=None, direction="lower_is_better"):
    """
    ממפה ערך לציון 0..1 לפי threshold_window.
    - אם lower_is_better: value <= target_max → 1.0 ; value >= cutoff_max → 0.0 ; ביניהם – אינטרפולציה ליניארית יורדת.
    - אם higher_is_better: value >= target_min → 1.0 ; value <= cutoff_min → 0.0 ; ביניהם – אינטרפולציה ליניארית עולה.
    """
    if direction == "lower_is_better":
        assert target_max is not None and cutoff_max is not None
        if value <= target_max:
            return 1.0
        if value >= cutoff_max:
            return 0.0
        # ליניארי בין target_max..cutoff_max
        t = (value - target_max) / (cutoff_max - target_max)
        return max(0.0, min(1.0, 1.0 - t))
    else:
        assert target_min is not None and cutoff_min is not None
        if value >= target_min:
            return 1.0
        if value <= cutoff_min:
            return 0.0
        t = (value - cutoff_min) / (target_min - cutoff_min)
        return max(0.0, min(1.0, t))

def eval_boolean_flag(flag_value, true_score=0.4, false_score=1.0):
    """boolean_flag: אם יש דגל (True/1) → true_score, אחרת false_score."""
    return true_score if _truthy(flag_value) else false_score

def weighted_mean(pairs):
    """pairs = [(score, weight), ...]"""
    num = sum(s * w for s, w in pairs)
    den = sum(w for _, w in pairs) or 1e-9
    return num / den

# ------------------------------ Tests ------------------------------

def test_files_exist_and_loadable():
    base = load_yaml(BASE)
    bw = load_yaml(BW)
    assert base["id"] == "squat.base"
    assert bw["id"] == "squat.bodyweight.md"
    assert bw.get("extends") == "squat.base"

def test_autodetect_bodyweight_when_no_bar_present():
    bw = load_yaml(BW)
    hints = bw["match_hints"]

    # סימולציה: אין ציוד מזוהה, יש זיהוי תנוחה בסיסי
    meas_ok = {
        "pose.available": True,
        "objdet.bar_present": False
    }
    assert matches_hints(hints, meas_ok) is True, "Should match bodyweight when no bar is present"

    # אם יש מוט — אסור להתאים ל-bodyweight
    meas_with_bar = {
        "pose.available": True,
        "objdet.bar_present": True
    }
    assert matches_hints(hints, meas_with_bar) is False, "Should NOT match bodyweight when a bar is detected"

def test_depth_scoring_increases_until_85_then_saturates():
    bw = load_yaml(BW)
    depth_rule = bw["scoring"]["criteria"]["depth"]["rule"]
    assert depth_rule["kind"] == "threshold_window"
    assert depth_rule["direction"] == "lower_is_better"
    target_max = depth_rule["target_max"]     # 85
    cutoff_max = depth_rule["cutoff_max"]     # 150

    # ערכים לדוגמה: רדוד → בינוני → עמוק (זווית ברך קטנה = עמוק יותר)
    v_shallow = 140
    v_mid     = 100
    v_target  = 85
    v_beyond  = 80  # עמוק יותר מהיעד – לא אמור להעלות מעבר ל-1.0

    s_shallow = eval_threshold_window(v_shallow, target_max=target_max, cutoff_max=cutoff_max, direction="lower_is_better")
    s_mid     = eval_threshold_window(v_mid,     target_max=target_max, cutoff_max=cutoff_max, direction="lower_is_better")
    s_target  = eval_threshold_window(v_target,  target_max=target_max, cutoff_max=cutoff_max, direction="lower_is_better")
    s_beyond  = eval_threshold_window(v_beyond,  target_max=target_max, cutoff_max=cutoff_max, direction="lower_is_better")

    assert 0.0 <= s_shallow < s_mid < s_target <= 1.0
    assert s_target == 1.0
    assert s_beyond == 1.0, "Going past 85° should not raise score above 1.0"

def test_heels_grounded_penalty_applies():
    bw = load_yaml(BW)
    heels = bw["scoring"]["criteria"]["heels_grounded"]
    weight = heels["weight"]
    rule   = heels["rule"]
    assert rule["kind"] == "boolean_flag"

    # אין הרמת עקבים
    score_ok = eval_boolean_flag(flag_value=0, true_score=rule["true_score"], false_score=rule["false_score"])
    # יש הרמת עקבים
    score_bad = eval_boolean_flag(flag_value=1, true_score=rule["true_score"], false_score=rule["false_score"])

    assert score_ok == rule["false_score"] == 1.0
    assert math.isclose(score_bad, rule["true_score"], rel_tol=1e-9)

    # בדיקת תרומה משוקללת לדוגמה
    overall = weighted_mean([(score_ok, weight), (1.0, 1.0)])  # עוד קריטריון מושלם
    overall_bad = weighted_mean([(score_bad, weight), (1.0, 1.0)])
    assert overall_bad < overall, "Heel lift should reduce the overall score when weighted"

def test_safety_cap_triggers_on_spine_rounding():
    base = load_yaml(BASE)
    safety_caps = base["scoring"]["safety_caps"]
    # מאתרים cap עבור spine_rounding ≤ 0.6
    cap_item = next((c for c in safety_caps if "spine_rounding" in c["when"]), None)
    assert cap_item is not None
    cap_value = cap_item["cap"]
    assert 0 < cap_value < 1

    # סימולציית ניקוד: ניקח ציון "היפותטי" גבוה, אבל spine_rounding גרוע (ציון 0.6 ומטה)
    raw_overall = 0.95
    spine_rounding_score = 0.5  # גרוע → מפעיל cap
    capped_overall = min(raw_overall, cap_value) if spine_rounding_score <= 0.6 else raw_overall
    assert math.isclose(capped_overall, cap_value, rel_tol=1e-9), "Overall score should be capped when spine rounding is poor"
