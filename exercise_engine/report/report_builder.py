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
    # (code, predicate, level, message_fn)
    ("NO_EXERCISE",      lambda r: r.get("exercise") is None,                               "FAIL", "לא זוהה תרגיל. בדוק classifier/aliases."),
    ("UNSCORED",         lambda r: r.get("scoring", {}).get("score") is None,               "WARN", "לא חושב ציון (unscored)."),
    ("LOW_COVERAGE",     lambda r: (r.get("coverage", {}).get("available_pct", 100) < 60),  "WARN", "זמינות נמוכה (coverage<60%)."),
    ("MISSING_CRITICAL", lambda r: len(r.get("coverage", {}).get("missing_critical", []))>0,"FAIL", "חסרים קריטריונים קריטיים."),
    ("CAMERA_RISK",      lambda r: bool(r.get("camera", {}).get("visibility_risk", False)),"WARN", "תנאי צילום גבוליים — ייתכנו סטיות במדידה."),
    ("LOW_QUALITY",      lambda r: r.get("scoring", {}).get("quality") == "poor",           "WARN", "איכות שקלול נמוכה (poor)."),
    # אינדיקציות לפי diagnostics:
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
            # לא חוסם דו"ח — לכל היותר נוסיף אינדיקציה כללית
            issues.append({"code": "HEALTH_RULE_ERROR", "level": "WARN", "message": f"כלל אינדיקציה נכשל: {code}"})
            worst = "WARN" if worst != "FAIL" else worst
    return {"status": worst, "issues": issues}

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
    # אופציונלי: אוספים מוכנים של סטים/חזרות (אם קיימים אצלך ברנטיים)
    sets: Optional[List[Dict[str, Any]]] = None,
    reps: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:

    applied_caps: List[Dict[str, Any]] = []
    final_score = overall_score

    # Safety caps (אם הוגדרו ב-YAML של התרגיל)
    if exercise and overall_score is not None and isinstance(per_criterion_scores, dict):
        final_score, applied_caps = _apply_safety_caps(exercise, overall_score, per_criterion_scores)

    # רשימת קריטריונים לתצוגה (כולל score/score_pct לכל קריטריון)
    criteria_list: List[Dict[str, Any]] = []
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
        # נשיכת הציון אם קיים ב-per_criterion_scores
        if isinstance(per_criterion_scores, dict) and name in per_criterion_scores:
            try:
                sc = getattr(per_criterion_scores[name], "score", None)
                if sc is not None:
                    item["score"] = float(sc)
                    item["score_pct"] = _to_pct(sc)
            except Exception:
                pass
        criteria_list.append(item)

    coverage = _compute_coverage(exercise, availability)

    # מטא + טווחי צבע ל-UI (פס צבעוני מתחת לעיגול)
    ui_ranges = {
        "color_bar": [
            {"label": "red",   "from_pct": 0,  "to_pct": 60},
            {"label": "orange","from_pct": 60, "to_pct": 75},
            {"label": "green", "from_pct": 75, "to_pct": 100},
        ]
    }

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
            "score": final_score,                 # 0..1 או None
            "score_pct": _to_pct(final_score),    # 0..100 או None
            "quality": overall_quality,           # full/partial/poor
            "unscored_reason": unscored_reason,
            # אין Grade במערכת
            "applied_caps": applied_caps,         # אם הוחלו caps
            "criteria": criteria_list,            # כולל score_pct לכל קריטריון
        },
        "coverage": coverage,
        "hints": list(hints or []),
        "diagnostics": diagnostics_recent[-50:] if isinstance(diagnostics_recent, list) else [],
        "measurements": dict(canonical or {}),
    }

    # ---------------------------------------------------------------------
    # canonical שטוח + בלוק rep היררכי (לשיחזור ולדשבורד)
    # ---------------------------------------------------------------------
    try:
        canonical_block = {}
        rep_block = {}
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

    # ---------------------------------------------------------------------
    # sets[] / reps[] — אם הועברו (לא חובה; תואם UI מפורט)
    # ---------------------------------------------------------------------
    if isinstance(sets, list) and sets:
        report["sets"] = sets
    if isinstance(reps, list) and reps:
        report["reps"] = reps

    # ---------------------------------------------------------------------
    # Report Health — אינדיקציות חכמות (OK/WARN/FAIL)
    # ---------------------------------------------------------------------
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
