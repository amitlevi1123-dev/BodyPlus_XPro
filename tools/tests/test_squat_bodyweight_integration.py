# tools/tests/test_squat_bodyweight_integration.py
# pytest -q

import math
import yaml
from pathlib import Path

# --- נתיבים כפי שביקשת (Windows) ---
BASE = Path(r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro\exercise_library\exercises\_base\squat.base.yaml")
BW   = Path(r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro\exercise_library\exercises\packs\bodyweight\squat\squat_bodyweight.yaml")

# -------------------- Utilities --------------------

def load_yaml(p: Path):
    assert p.exists(), f"Missing file: {p}"
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def weighted_mean(pairs):
    # pairs: list[(score, weight)]
    num = sum(s * w for s, w in pairs)
    den = sum(w for _, w in pairs) or 1e-9
    return num / den

def clamp01(x): return max(0.0, min(1.0, float(x)))

def truthy(v):
    if isinstance(v, bool): return v
    if v is None: return False
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, str): return v.strip() != ""
    return True

# -------------------- Rule evaluators --------------------

def eval_rule(rule: dict, meas: dict) -> float:
    kind = rule["kind"]
    if kind == "threshold_window":
        direction = rule.get("direction", "lower_is_better")
        value = _eval_input(rule["input"], meas)
        if direction == "lower_is_better":
            target_max = rule["target_max"]; cutoff_max = rule["cutoff_max"]
            if value <= target_max: return 1.0
            if value >= cutoff_max: return 0.0
            t = (value - target_max) / (cutoff_max - target_max)
            return clamp01(1.0 - t)
        else:
            target_min = rule["target_min"]; cutoff_min = rule["cutoff_min"]
            if value >= target_min: return 1.0
            if value <= cutoff_min: return 0.0
            t = (value - cutoff_min) / (target_min - cutoff_min)
            return clamp01(t)

    if kind == "tempo_window":
        value = _eval_input(rule["input"], meas)
        lo, hi = rule["min"], rule["max"]
        c_lo, c_hi = rule["cutoff_min"], rule["cutoff_max"]
        if value < c_lo or value > c_hi: return 0.0
        if lo <= value <= hi: return 1.0
        if value < lo:
            # מדרג ליניארי בין cutoff_min..min
            return clamp01((value - c_lo) / (lo - c_lo))
        else:
            # מדרג ליניארי בין max..cutoff_max
            return clamp01((c_hi - value) / (c_hi - hi))

    if kind == "band_center":
        v = _eval_input(rule["input"], meas)
        lo_ok, hi_ok = rule["min_ok"], rule["max_ok"]
        c_lo, c_hi = rule["cutoff_min"], rule["cutoff_max"]
        if v < c_lo or v > c_hi: return 0.0
        if lo_ok <= v <= hi_ok: return 1.0
        if v < lo_ok:
            return clamp01((v - c_lo) / (lo_ok - c_lo))
        else:
            return clamp01((c_hi - v) / (c_hi - hi_ok))

    if kind == "linear_band":
        v = _eval_input(rule["input"], meas)
        good, ok, bad = rule["good_max"], rule["ok_max"], rule["bad_max"]
        # ≤good → 1.0 ; ≥bad → 0.0 ; בין good..ok..bad ירידה ליניארית
        if v <= good: return 1.0
        if v >= bad: return 0.0
        # good..ok → ירידה מתונה; ok..bad → ירידה נוספת
        if v <= ok:
            return clamp01(1.0 - (v - good) / (ok - good))
        return clamp01(1.0 - ( (ok - good) / (ok - good) + (v - ok) / (bad - ok) )/2.0)  # מדרג דו-שלבי מתון

    if kind == "symmetric_threshold":
        v = abs(_eval_input(rule["input"], meas))
        ok, warn, bad = rule["ok"], rule["warn"], rule["bad"]
        if v <= ok: return 1.0
        if v >= bad: return 0.0
        # אינטרפולציה ליניארית בין ok..bad
        return clamp01(1.0 - (v - ok) / (bad - ok))

    if kind == "boolean_flag":
        v = _eval_input(rule["input"], meas)
        return rule.get("true_score", 0.4) if truthy(v) else rule.get("false_score", 1.0)

    raise NotImplementedError(f"Unsupported rule kind: {kind}")

def _eval_input(expr: str, meas: dict) -> float:
    """
    תומך בביטויים פשוטים שמופיעים ב-YAML:
    - "min(a, b)"
    - "max(a, b)"
    - "mean(abs(a), abs(b))"
    - "abs(x)"
    - או מפתח בודד "rep.timing_s" / "features.stance_width_ratio" וכו׳
    """
    expr = expr.strip()
    # פונקציות נפוצות
    if expr.startswith("min(") and expr.endswith(")"):
        args = [x.strip() for x in expr[4:-1].split(",")]
        return min(_eval_input(a, meas) for a in args)
    if expr.startswith("max(") and expr.endswith(")"):
        args = [x.strip() for x in expr[4:-1].split(",")]
        return max(_eval_input(a, meas) for a in args)
    if expr.startswith("mean(") and expr.endswith(")"):
        args = [x.strip() for x in expr[5:-1].split(",")]
        vals = [_eval_input(a, meas) for a in args]
        return sum(vals) / max(1, len(vals))
    if expr.startswith("abs(") and expr.endswith(")"):
        inner = expr[4:-1].strip()
        return abs(_eval_input(inner, meas))
    # מפתח יחיד
    assert expr in meas, f"Missing measurement key: {expr}"
    return float(meas[expr])

# -------------------- Merge base ← bodyweight --------------------

def merged_criteria_and_caps(base_yaml: dict, bw_yaml: dict):
    base_c = base_yaml["scoring"]["criteria"]
    bw_c = bw_yaml.get("scoring", {}).get("criteria", {})
    # ירושה: מעתיקים מהבסיס, ומעדכנים/מחליפים לפי bodyweight
    merged = {k: dict(v) for k, v in base_c.items()}
    for k, v in bw_c.items():
        merged[k] = dict(v)
    # Safety caps מגיעים מה-base (ל-bodyweight לא הוגדרו חדשים)
    caps = base_yaml["scoring"].get("safety_caps", [])
    return merged, caps

def apply_safety_caps(overall: float, safety_caps: list, scores_by_name: dict) -> float:
    # safety_caps: דוגמה {"when": "spine_rounding <= 0.6", "cap": 0.70}
    capped = overall
    for cap in safety_caps:
        cond = cap["when"]
        cap_val = cap["cap"]
        # תמיכה בסיסית בביטוי "name <= value"
        if "<=" in cond:
            name, val = [x.strip() for x in cond.split("<=")]
            if name in scores_by_name and scores_by_name[name] <= float(val):
                capped = min(capped, cap_val)
        elif "<" in cond:
            name, val = [x.strip() for x in cond.split("<")]
            if name in scores_by_name and scores_by_name[name] < float(val):
                capped = min(capped, cap_val)
        elif ">=" in cond:
            name, val = [x.strip() for x in cond.split(">=")]
            if name in scores_by_name and scores_by_name[name] >= float(val):
                capped = min(capped, cap_val)
        elif ">" in cond:
            name, val = [x.strip() for x in cond.split(">")]
            if name in scores_by_name and scores_by_name[name] > float(val):
                capped = min(capped, cap_val)
    return capped

# -------------------- Tests --------------------

def test_integration_good_set_scores_high_without_caps():
    base = load_yaml(BASE)
    bw = load_yaml(BW)
    criteria, caps = merged_criteria_and_caps(base, bw)

    # סט "טוב" — אמור לקבל ציון גבוה ללא הפעלת Caps
    meas = {
        "pose.available": True,
        "objdet.bar_present": False,

        # עומק (עמוק וטוב, מעט מעל היעד כדי לראות אינטרפולציה קלה)
        "knee_left_deg": 88.0,
        "knee_right_deg": 90.0,

        # בטיחות
        "spine_flexion_deg": 8.0,              # עגילת גב קטנה
        "spine_curvature_side_deg": 2.0,       # עיקום צדדי קטן
        "knee_foot_alignment_left_deg": 3.0,   # ולגוס נמוך
        "knee_foot_alignment_right_deg": 4.0,

        # טכניקה
        "features.stance_width_ratio": 1.0,
        "toe_angle_left_deg": 12.0,
        "toe_angle_right_deg": 14.0,
        "head_pitch_deg": 8.0,
        "rep.timing_s": 1.5,
        "heel_lift_left": 0,
        "heel_lift_right": 0,

        # לפונקציות עזר בביטויים אם נידרש
        "hip_y_px": 200,
    }

    pairs = []
    scores_by_name = {}
    for name, cfg in criteria.items():
        rule = cfg["rule"]
        weight = cfg.get("weight", 0.0)
        # skip קריטריונים עם weight==0 (למשל dorsiflexion אצלך)
        if weight <= 0:
            continue
        try:
            s = eval_rule(rule, meas)
        except AssertionError:
            # חסר מפתח למדידה → "missing: skip"
            continue
        scores_by_name[name] = s
        pairs.append((s, weight))

    overall = weighted_mean(pairs)
    capped = apply_safety_caps(overall, caps, scores_by_name)

    # ציפיות: ציון גבוה מאוד, ללא קאפ (כי כל קריטריון בטיחות > 0.6)
    assert overall > 0.85, f"Expected high score, got {overall:.3f}"
    assert math.isclose(capped, overall, rel_tol=1e-9), "Cap should not apply on good set"

def test_integration_bad_spine_triggers_cap():
    base = load_yaml(BASE)
    bw = load_yaml(BW)
    criteria, caps = merged_criteria_and_caps(base, bw)

    # סט עם עיגול גב משמעותי → אמור להפעיל Cap (0.70 לפי ה-base)
    meas = {
        "pose.available": True,
        "objdet.bar_present": False,

        # עומק ופרמטרים אחרים טובים
        "knee_left_deg": 90.0,
        "knee_right_deg": 90.0,
        "features.stance_width_ratio": 1.0,
        "toe_angle_left_deg": 10.0,
        "toe_angle_right_deg": 12.0,
        "head_pitch_deg": 10.0,
        "rep.timing_s": 1.2,
        "heel_lift_left": 0,
        "heel_lift_right": 0,

        # בטיחות — עיגול גב גדול
        "spine_flexion_deg": 30.0,            # זה אמור להוריד את spine_rounding משמעותית
        "spine_curvature_side_deg": 3.0,
        "knee_foot_alignment_left_deg": 4.0,
        "knee_foot_alignment_right_deg": 5.0,
    }

    pairs = []
    scores_by_name = {}
    for name, cfg in criteria.items():
        rule = cfg["rule"]
        weight = cfg.get("weight", 0.0)
        if weight <= 0:
            continue
        try:
            s = eval_rule(rule, meas)
        except AssertionError:
            continue
        scores_by_name[name] = s
        pairs.append((s, weight))

    overall = weighted_mean(pairs)
    capped = apply_safety_caps(overall, caps, scores_by_name)

    # מאמתים שה-cap של spine_rounding הופעל
    assert capped <= overall
    # cap צפוי להיות סביב 0.70 (לפי base). לא ננעל לערך מדויק — רק לוודא שקרוב.
    assert capped <= 0.71, f"Expected cap near 0.70, got {capped:.3f}"

def test_integration_heels_lift_reduces_score():
    base = load_yaml(BASE)
    bw = load_yaml(BW)
    criteria, caps = merged_criteria_and_caps(base, bw)

    # שני מצבים זהים – רק הבדל בעקב
    good_meas = {
        "pose.available": True, "objdet.bar_present": False,
        "knee_left_deg": 90.0, "knee_right_deg": 90.0,
        "spine_flexion_deg": 10.0, "spine_curvature_side_deg": 4.0,
        "knee_foot_alignment_left_deg": 5.0, "knee_foot_alignment_right_deg": 5.0,
        "features.stance_width_ratio": 1.0,
        "toe_angle_left_deg": 12.0, "toe_angle_right_deg": 12.0,
        "head_pitch_deg": 10.0,
        "rep.timing_s": 1.4,
        "heel_lift_left": 0, "heel_lift_right": 0,
    }
    bad_meas = dict(good_meas)
    bad_meas.update({"heel_lift_left": 1})

    def eval_overall(meas):
        pairs = []
        scores = {}
        for name, cfg in criteria.items():
            rule = cfg["rule"]; weight = cfg.get("weight", 0.0)
            if weight <= 0: continue
            try:
                s = eval_rule(rule, meas)
            except AssertionError:
                continue
            scores[name] = s
            pairs.append((s, weight))
        overall = weighted_mean(pairs)
        overall = apply_safety_caps(overall, caps, scores)
        return overall

    s_good = eval_overall(good_meas)
    s_bad  = eval_overall(bad_meas)

    assert s_bad < s_good, f"Heel lift should reduce score. good={s_good:.3f}, bad={s_bad:.3f}"
