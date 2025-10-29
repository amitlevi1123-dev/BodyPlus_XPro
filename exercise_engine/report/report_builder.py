# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 📘 report_builder.py — בניית דוחות סופיים לממשק המשתמש (UI)
# -----------------------------------------------------------------------------
# שינויי מפתח:
# • אין Grade במערכת.
# • criteria כוללים score ו-score_pct (ל-tooltip פירוק קריטריונים).
# • הוספת report_health חכם: OK/WARN/FAIL + issues[].
# • תמיכה אופציונלית ב-sets[] ו-reps[] (נשלחים מבחוץ; לא חובה).
# • שמירת canonical ו-rep היררכי (נשמר).
# • שמירת camera + הזרקת הודעת ריסק כרמז (נשמר).
# • הוספת ui_ranges לפס הצבעוני (אדום/כתום/ירוק).
# • NEW: criteria_breakdown_pct (מפה ידידותית ל-Tooltip).
# • NEW: quality ברירת מחדל ל-"partial" אם לא ניתן.
# • NEW: metrics_detail — תקציר מפורט של ערכים רלוונטיים (טמפו/זוויות/עמידה/יעדים).
#    • איסוף חכם של מפתחות רלוונטיים לפי criteria.requires (משפחה + וריאציה)
#    • סינון לפי מה שקיים בפועל ב-canonical (בלי “ידיים בתרגיל רגליים”)
#    • טמפו לכל חזרה, אם קיים מבנה rep.*
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, cast
from collections import Counter

# ---------------------------- Utilities ----------------------------

def _safe_float(x, default=None):
    try:
        return float(x)
    except Exception:
        return default

def _to_pct(x: Optional[float]) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(round(float(x) * 100.0))
    except Exception:
        return None

def _eval_cap_condition(expr: str, per_scores: Dict[str, Any]) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    if not isinstance(expr, str):
        return (None, None, None)
    parts = expr.strip().split()
    if len(parts) != 3:
        return (None, None, None)
    crit, op, sval = parts[0], parts[1], parts[2]
    if op not in ("<=", "<", ">=", ">", "=="):
        return (None, None, None)
    c = per_scores.get(crit)
    score_val = None
    try:
        score_val = float(getattr(c, "score", None))
    except Exception:
        score_val = None
    try:
        rhs = float(sval)
    except Exception:
        return (None, None, None)
    ok = False
    if score_val is not None:
        if   op == "<=": ok = score_val <= rhs
        elif op == "<":  ok = score_val <  rhs
        elif op == ">=": ok = score_val >= rhs
        elif op == ">":  ok = score_val >  rhs
        elif op == "==": ok = abs(score_val - rhs) < 1e-9
    return (crit, score_val if ok else None, op)

def _apply_safety_caps(exercise, overall: Optional[float], per_scores: Dict[str, Any]) -> (Optional[float], List[Dict[str, Any]]):
    out_caps: List[Dict[str, Any]] = []
    if overall is None:
        return overall, out_caps
    caps = getattr(exercise, "safety_caps", None) or []
    new_overall = overall
    for item in caps:
        try:
            cond = str(item.get("when", "")).strip()
            cap_val = float(item.get("cap"))
        except Exception:
            continue
        crit, actual, _op = _eval_cap_condition(cond, per_scores)
        if actual is None:
            continue
        before = new_overall
        new_overall = min(new_overall, cap_val)
        out_caps.append({
            "when": cond,
            "cap": cap_val,
            "reason": f"{cond}",
            "actual": actual,
            "before": before,
            "after": new_overall,
        })
    return new_overall, out_caps

def _compute_coverage(exercise, availability: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """ מחשב מדדי כיסוי על בסיס קריטריונים והזמינות בפועל. """
    crit_defs = getattr(exercise, "criteria", {}) if exercise is not None else {}
    crit_ids = list(crit_defs.keys()) if isinstance(crit_defs, dict) else list(availability.keys())
    total = len(crit_ids)

    available_count = 0
    reasons: List[str] = []
    for cid in crit_ids:
        info = availability.get(cid, {}) if isinstance(availability, dict) else {}
        is_avail = bool(info.get("available", False))
        if is_avail:
            available_count += 1
        else:
            r = info.get("reason")
            reasons.append(str(r) if r else "not_provided")

    ratio = (available_count / total) if total > 0 else 0.0
    pct = int(round(ratio * 100.0))

    critical = list(getattr(exercise, "critical", []) or []) if exercise else []
    missing_critical = [cid for cid in critical if not bool(availability.get(cid, {}).get("available", False))]

    top_reasons = []
    if reasons:
        cnt = Counter(reasons)
        top_reasons = [name for name, _n in cnt.most_common(3)]

    return {
        "available_ratio": float(ratio),
        "available_pct": int(pct),
        "available_count": int(available_count),
        "total_criteria": int(total),
        "missing_reasons_top": top_reasons,
        "missing_critical": missing_critical,
    }

# ---------------------------- Report Health ----------------------------

_HEALTH_RULES = [
    ("NO_EXERCISE",      lambda r: r.get("exercise") is None,                               "FAIL", "לא זוהה תרגיל. בדוק classifier/aliases."),
    ("UNSCORED",         lambda r: r.get("scoring", {}).get("score") is None,               "WARN", "לא חושב ציון (unscored)."),
    ("LOW_COVERAGE",     lambda r: (r.get("coverage", {}).get("available_pct", 100) < 60),  "WARN", "זמינות נמוכה (coverage<60%)."),
    ("MISSING_CRITICAL", lambda r: len(r.get("coverage", {}).get("missing_critical", []))>0,"FAIL", "חסרים קריטריונים קריטיים."),
    ("CAMERA_RISK",      lambda r: bool(r.get("camera", {}).get("visibility_risk", False)),"WARN", "תנאי צילום גבוליים — ייתכנו סטיות במדידה."),
    ("LOW_QUALITY",      lambda r: r.get("scoring", {}).get("quality") == "poor",           "WARN", "איכות שקלול נמוכה (poor)."),
    ("ALIAS_CONFLICTS",  lambda r: any(d.get("type")=="alias_conflict" for d in r.get("diagnostics", [])),"WARN","התנגשות ערכים בין אליאסים."),
    ("SET_COUNTER_ERROR",lambda r: any(d.get("type")=="set_counter_error" for d in r.get("diagnostics", [])),"WARN","שגיאת ספירת סטים."),
    ("REP_ENGINE_ERROR", lambda r: any(d.get("type")=="rep_segmenter_error" for d in r.get("diagnostics", [])),"WARN","שגיאת מנוע חזרות."),
]

def _compute_report_health(report: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    levels = {"OK":0,"WARN":1,"FAIL":2}
    worst = "OK"
    for code, pred, level, msg in _HEALTH_RULES:
        try:
            if pred(report):
                issues.append({"code": code, "level": level, "message": msg})
                if levels[level] > levels[worst]:
                    worst = level
        except Exception:
            issues.append({"code": "HEALTH_RULE_ERROR", "level": "WARN", "message": f"כלל אינדיקציה נכשל: {code}"})
            worst = "WARN" if worst != "FAIL" else worst
    return {"status": worst, "issues": issues}

# ---------------------------- Metrics Detail (NEW) ----------------------------

# מפתחות "תמיד מעניינים" להצגה אם קיימים ב-canonical
_ALWAYS_KEYS = [
    # טמפו/חזרות
    "rep.timing_s", "rep.ecc_s", "rep.con_s", "rep.pause_top_s", "rep.pause_bottom_s",
    # גו/עמוד שדרה
    "torso_forward_deg", "spine_flexion_deg", "spine_curvature_side_deg",
    # עמידה/כפות רגליים
    "features.stance_width_ratio", "toe_angle_left_deg", "toe_angle_right_deg",
    "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
    "heels_grounded", "foot_contact_left", "foot_contact_right",
]

# קבוצות להצגה נעימה ב-UI
_GROUPS = {
    "tempo": [
        "rep.timing_s", "rep.ecc_s", "rep.con_s", "rep.pause_top_s", "rep.pause_bottom_s"
    ],
    "joints": [
        "knee_left_deg", "knee_right_deg",
        "hip_left_deg", "hip_right_deg",
        "torso_forward_deg", "spine_flexion_deg", "spine_curvature_side_deg",
        "head_pitch_deg", "head_yaw_deg", "head_roll_deg",
        "elbow_left_deg", "elbow_right_deg", "shoulder_left_deg", "shoulder_right_deg",
        "ankle_dorsi_left_deg", "ankle_dorsi_right_deg",
    ],
    "stance": [
        "features.stance_width_ratio",
        "toe_angle_left_deg", "toe_angle_right_deg",
        "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
        "heels_grounded", "foot_contact_left", "foot_contact_right",
    ],
}

def _gather_required_keys(exercise) -> List[str]:
    """
    מאחד את כל requires מכל הקריטריונים של התרגיל (כפי שהוא נטען — כולל ירושה מה-base).
    """
    out: List[str] = []
    crit = getattr(exercise, "criteria", {}) or {}
    if isinstance(crit, dict):
        for cid, cdef in crit.items():
            req = (cdef or {}).get("requires")
            if isinstance(req, list):
                for k in req:
                    if isinstance(k, str):
                        out.append(k)
    # הוספת always
    out.extend(_ALWAYS_KEYS)
    # ייחוד ושמירת סדר (בסיסי)
    seen = set()
    uniq: List[str] = []
    for k in out:
        if k not in seen:
            uniq.append(k); seen.add(k)
    return uniq

def _present_keys(canonical: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    """ מחזיר רק מפתחות שיש להם ערך ב-canonical (לא None). """
    out: Dict[str, Any] = {}
    for k in keys:
        if k in canonical:
            v = canonical.get(k)
            if v is not None:
                out[k] = v
    return out

def _extract_rep_series(rep_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    בונה רשימה per-rep עבור טמפו אם יש מבנה rep.* היררכי.
    תומך בשני מצבים:
      • ערכים סקלריים — מחזיר חזרה אחת (אם אין אינדקסים)
      • ערכים כרשימות/מילונים — מנסה ליישר על פי אינדקסים/מפתחות
    """
    if not isinstance(rep_tree, dict) or not rep_tree:
        return []

    # נאתר שדות עיקריים
    timing = rep_tree.get("timing_s")
    ecc = rep_tree.get("ecc_s")
    con = rep_tree.get("con_s")
    ptop = rep_tree.get("pause_top_s")
    pbot = rep_tree.get("pause_bottom_s")
    rep_id = rep_tree.get("rep_id")

    # אם הכל סקלרי — מחזירים רשומה אחת
    def _is_scalar(x):
        return not isinstance(x, (list, dict))

    all_fields = [timing, ecc, con, ptop, pbot, rep_id]
    if any(f is not None for f in all_fields) and all((_is_scalar(f) or f is None) for f in all_fields):
        return [{
            "rep_id": rep_id if rep_id is not None else 1,
            "timing_s": timing, "ecc_s": ecc, "con_s": con,
            "pause_top_s": ptop, "pause_bottom_s": pbot,
        }]

    # אחרת — ננסה לאחד לפי אינדקס
    # תמיכה בסיסית: אם שדה הוא list — משתמשים באינדקס; אם dict — לפי מפתחות ממוינים
    def _to_indexed_list(x):
        if isinstance(x, list):
            return list(enumerate(x, start=1))
        if isinstance(x, dict):
            # ממיינים לפי מפתח אם ניתן
            try:
                items = sorted(x.items(), key=lambda kv: (str(kv[0])))
            except Exception:
                items = list(x.items())
            return [(int(k) if str(k).isdigit() else k, v) for k, v in items]
        if x is None:
            return []
        # סקלר → חזרה יחידה
        return [(1, x)]

    idx_fields = {
        "timing_s": _to_indexed_list(timing),
        "ecc_s": _to_indexed_list(ecc),
        "con_s": _to_indexed_list(con),
        "pause_top_s": _to_indexed_list(ptop),
        "pause_bottom_s": _to_indexed_list(pbot),
        "rep_id": _to_indexed_list(rep_id),
    }

    # איחוד כל האינדקסים האפשריים
    all_idxs = set()
    for pairs in idx_fields.values():
        for i, _ in pairs:
            all_idxs.add(i)
    if not all_idxs:
        return []

    def _val(pairs, i):
        for ii, vv in pairs:
            if ii == i:
                return vv
        return None

    rows: List[Dict[str, Any]] = []
    for i in sorted(all_idxs, key=lambda z: (isinstance(z, int) is False, z)):
        rows.append({
            "rep_id": _val(idx_fields["rep_id"], i) or i,
            "timing_s": _val(idx_fields["timing_s"], i),
            "ecc_s": _val(idx_fields["ecc_s"], i),
            "con_s": _val(idx_fields["con_s"], i),
            "pause_top_s": _val(idx_fields["pause_top_s"], i),
            "pause_bottom_s": _val(idx_fields["pause_bottom_s"], i),
        })
    return rows

def build_auto_metrics_detail(*, exercise, canonical: Dict[str, Any], rep_tree: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    בונה בלוק "metrics_detail" להצגה ב-UI:
    • איסוף מפתחות רלוונטיים לפי criteria.requires (כולל base+variant) + ALWAYS
    • חלוקה לקבוצות: tempo / joints / stance
    • סדר אלגנטי והסתרת שדות חסרי ערך
    • פירוק טמפו per-rep אם rep_tree קיים
    """
    relevant_keys = _gather_required_keys(exercise)
    present_all = _present_keys(canonical, relevant_keys)

    # חלוקה לקבוצות
    grouped: Dict[str, Dict[str, Any]] = {}
    for gname, gkeys in _GROUPS.items():
        grouped[gname] = _present_keys(present_all, gkeys)

    # שאר השדות הרלוונטיים שלא נתפסו בקבוצות — נשמרים ב-"other"
    grouped_keys_flat = set(k for lst in _GROUPS.values() for k in lst)
    other_keys = [k for k in present_all.keys() if k not in grouped_keys_flat]
    grouped["other"] = _present_keys(present_all, other_keys)

    # פירוק חזרות (טמפו) אם יש rep.* היררכי
    rep_series: List[Dict[str, Any]] = []
    if isinstance(rep_tree, dict) and rep_tree:
        rep_series = _extract_rep_series(rep_tree)

    # יעדים (targets) — מציג רק מה שאפשר להבין ממנו מספרים “מעניינים”
    targets_block: Dict[str, Any] = {}
    try:
        t = getattr(exercise, "targets", None)
        if isinstance(t, dict) and t:
            # שולפים רק תתי-שדות מספריים כדי לא להציף
            def _num_only(d: Dict[str, Any]) -> Dict[str, Any]:
                out = {}
                for k, v in d.items():
                    if isinstance(v, (int, float)):
                        out[k] = v
                    elif isinstance(v, dict):
                        sub = _num_only(v)
                        if sub:
                            out[k] = sub
                return out
            targets_block = _num_only(t)
    except Exception:
        targets_block = {}

    # סטטיסטיקה קטנה לתצוגה (כמה ערכים הוצגו)
    stats = {
        "keys_available": len(present_all),
        "groups_non_empty": {k: bool(v) for k, v in grouped.items()},
        "has_rep_series": bool(rep_series),
    }

    return {
        "groups": grouped,
        "rep_tempo_series": rep_series,
        "targets": targets_block,
        "stats": stats,
    }

# ---------------------------- Report Builder ----------------------------

def build_payload(
    *,
    exercise,
    canonical: Dict[str, Any],
    availability: Dict[str, Dict[str, Any]],
    overall_score: Optional[float],
    overall_quality: Optional[str],
    unscored_reason: Optional[str],
    hints: List[str],
    diagnostics_recent: List[Dict[str, Any]],
    library_version: str,
    payload_version: str,
    per_criterion_scores: Optional[Dict[str, Any]] = None,
    sets: Optional[List[Dict[str, Any]]] = None,
    reps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:

    applied_caps: List[Dict[str, Any]] = []
    final_score = overall_score

    # Safety caps
    if exercise and overall_score is not None and isinstance(per_criterion_scores, dict):
        final_score, applied_caps = _apply_safety_caps(exercise, overall_score, per_criterion_scores)

    # criteria rows + flat breakdown for tooltip
    criteria_list: List[Dict[str, Any]] = []
    criteria_breakdown_pct: Dict[str, Optional[int]] = {}
    for name, info in (availability or {}).items():
        if not isinstance(info, dict):
            continue
        item = {
            "id": name,
            "available": bool(info.get("available", False)),
            "missing": list(info.get("missing", [])) if isinstance(info.get("missing"), list) else [],
            "reason": info.get("reason"),
            "score": None,
            "score_pct": None,
        }
        if isinstance(per_criterion_scores, dict) and name in per_criterion_scores:
            try:
                sc = getattr(per_criterion_scores[name], "score", None)
                if sc is not None:
                    item["score"] = float(sc)
                    item["score_pct"] = _to_pct(sc)
            except Exception:
                pass
        criteria_list.append(item)
        # breakdown map (only if available & has score_pct)
        if item["available"]:
            criteria_breakdown_pct[name] = item["score_pct"]
        else:
            criteria_breakdown_pct[name] = None

    coverage = _compute_coverage(exercise, availability)

    ui_ranges = {
        "color_bar": [
            {"label": "red",    "from_pct": 0,  "to_pct": 60},
            {"label": "orange", "from_pct": 60, "to_pct": 75},
            {"label": "green",  "from_pct": 75, "to_pct": 100},
        ]
    }

    # default quality
    quality_effective = overall_quality or ("partial" if final_score is not None else None)

    report: Dict[str, Any] = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "payload_version": str(payload_version),
            "library_version": str(library_version),
        },
        "exercise": None if exercise is None else {
            "id": exercise.id,
            "family": getattr(exercise, "family", None),
            "equipment": getattr(exercise, "equipment", None),
            "display_name": getattr(exercise, "display_name", exercise.id),
        },
        "ui_ranges": ui_ranges,
        "scoring": {
            "score": final_score,
            "score_pct": _to_pct(final_score),
            "quality": quality_effective,             # <- ברירת מחדל "partial"
            "unscored_reason": unscored_reason,
            "applied_caps": applied_caps,
            "criteria": criteria_list,
            "criteria_breakdown_pct": criteria_breakdown_pct,  # <- חדש ל-Tooltip
        },
        "coverage": coverage,
        "hints": list(hints or []),
        "diagnostics": diagnostics_recent[-50:] if isinstance(diagnostics_recent, list) else [],
        "measurements": dict(canonical or {}),
    }

    # canonical + rep tree
    rep_block = {}
    try:
        canonical_block = {}
        for k, v in (canonical or {}).items():
            if isinstance(k, str):
                canonical_block[k] = v
                if k.startswith("rep."):
                    parts = k.split(".")[1:]
                    d = rep_block
                    for part in parts[:-1]:
                        d = d.setdefault(part, {})
                    d[parts[-1]] = v
        if canonical_block:
            report["canonical"] = canonical_block
        if rep_block:
            report["rep"] = rep_block
    except Exception:
        pass

    # sets / reps (optional)
    if isinstance(sets, list) and sets:
        report["sets"] = sets
    if isinstance(reps, list) and reps:
        report["reps"] = reps

    # NEW: metrics_detail (נבנה מהתרגיל וה-canonical + rep_tree אם יש)
    try:
        report["metrics_detail"] = build_auto_metrics_detail(
            exercise=exercise,
            canonical=report.get("canonical", {}) or report.get("measurements", {}) or {},
            rep_tree=report.get("rep", None),
        )
    except Exception:
        # לא מפילים את הדו"ח בגלל פירוט — בטיחותית מתעלמים בשקט
        report["metrics_detail"] = {"error": "build_failed"}

    # health
    report["report_health"] = _compute_report_health(report)

    return report

# ---------------- Camera Summary Attach ----------------

def _normalize_camera_summary(camera_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """ מנרמל את סיכום המצלמה. """
    DEFAULT_OK = {
        "visibility_risk": False,
        "severity": "LOW",
        "message": "המדידה תקינה",
        "stats": {}
    }
    if not isinstance(camera_summary, dict) or not camera_summary:
        return DEFAULT_OK

    risk = bool(camera_summary.get("visibility_risk", False))
    severity = str(camera_summary.get("severity", "LOW") or "LOW").upper()
    message = camera_summary.get("message")
    if not message:
        message = "המדידה תקינה" if not risk else "הערה: תנאי צילום גבוליים — ייתכנו סטיות במדידה."
    stats = camera_summary.get("stats")
    if not isinstance(stats, dict):
        stats = {}

    out = {
        "visibility_risk": risk,
        "severity": severity,
        "message": str(message),
        "stats": cast(Dict[str, Any], stats),
    }
    for k in ("exercise", "set_index", "saved_at"):
        if k in camera_summary and k not in out:
            out[k] = camera_summary[k]
    return out

def attach_camera_summary(report: Dict[str, Any],
                          camera_summary: Optional[Dict[str, Any]],
                          *,
                          add_hint_if_risky: bool = True,
                          add_ok_hint_if_clean: bool = False,
                          save_json: bool = False,
                          meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    מצרף את סיכום המצלמה (camera_summary) אל דו"ח קיים:
    - מוסיף report["camera"] עם "המדידה תקינה" כברירת מחדל אם לא הועבר summary.
    - אם visibility_risk=True מוסיף הודעה ל-hints.
    - אם הכל תקין (clean) ומוגדר add_ok_hint_if_clean, מוסיף "המדידה תקינה".
    """
    cam = _normalize_camera_summary(camera_summary)
    hints = report.get("hints")
    if not isinstance(hints, list):
        hints = []
        report["hints"] = hints
    report["camera"] = cam
    msg = str(cam.get("message") or "")
    if cam.get("visibility_risk"):
        if add_hint_if_risky and msg and msg not in hints:
            hints.append(msg)
    else:
        if add_ok_hint_if_clean and msg and msg not in hints:
            hints.append(msg)
    if save_json:
        try:
            from exercise_engine.feedback.camera_wizard import save_set_audit  # type: ignore
            _ = save_set_audit(cam, add_meta=meta or {})
        except Exception:
            pass
    return report
