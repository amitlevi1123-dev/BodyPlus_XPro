# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 📘 report_builder.py — בניית דוחות סופיים לממשק המשתמש (UI)
# -----------------------------------------------------------------------------
# הסבר קצר (עברית):
# בניית דו"ח סופי ל-UI. תומך ב-Safety Caps, Grade Bands, ובשדות תצוגה:
# - score_pct (שלם 0..100) לציון הכללי
# - score_pct לכל קריטריון
# מוסיף בלוק Coverage שמסביר כמה קריטריונים היו זמינים ולמה חסרים:
#
# coverage = {
#   available_ratio: float (0..1),
#   available_pct: int (0..100),
#   available_count: int,
#   total_criteria: int,
#   missing_reasons_top: [str, ...] (עד טופ 3),
#   missing_critical: [criterion_id, ...]
# }
#
# חידוש:
# 1. פונקציית עזר לצירוף סיכום מצלמה (camera_summary) לדוח,
#    כולל ברירת מחדל "המדידה תקינה" אם אין הערות מיוחדות.
# 2. שמירה של כל המדדים הקנוניים (כולל rep.*) בתוך הדוח — גם שטוחים וגם בעץ.
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

def _compute_grade(overall: Optional[float], bands: Dict[str, float]) -> Optional[str]:
    if overall is None:
        return None
    a = _safe_float(bands.get("A"), 0.85)
    b = _safe_float(bands.get("B"), 0.75)
    c = _safe_float(bands.get("C"), 0.60)
    if overall >= a: return "A"
    if overall >= b: return "B"
    if overall >= c: return "C"
    return "D"

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
        if op == "<=": ok = score_val <= rhs
        elif op == "<": ok = score_val < rhs
        elif op == ">=": ok = score_val >= rhs
        elif op == ">": ok = score_val > rhs
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
        crit, actual, op = _eval_cap_condition(cond, per_scores)
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
) -> Dict[str, Any]:
    grade_bands = getattr(exercise, "grade_bands", {}) if exercise is not None else {}
    applied_caps: List[Dict[str, Any]] = []
    final_score = overall_score

    if exercise and overall_score is not None and isinstance(per_criterion_scores, dict):
        final_score, applied_caps = _apply_safety_caps(exercise, overall_score, per_criterion_scores)

    grade = _compute_grade(final_score, grade_bands) if final_score is not None else None

    criteria_list: List[Dict[str, Any]] = []
    for name, info in (availability or {}).items():
        if not isinstance(info, dict):
            continue
        criteria_list.append({
            "id": name,
            "available": bool(info.get("available", False)),
            "missing": list(info.get("missing", [])) if isinstance(info.get("missing"), list) else [],
            "reason": info.get("reason"),
            "score": None,
        })

    coverage = _compute_coverage(exercise, availability)

    report: Dict[str, Any] = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "payload_version": str(payload_version),
            "library_version": str(library_version),
        },
        "exercise": None if exercise is None else {
            "id": exercise.id,
            "family": exercise.family,
            "equipment": exercise.equipment,
            "display_name": getattr(exercise, "display_name", exercise.id),
        },
        "scoring": {
            "score": final_score,
            "score_pct": _to_pct(final_score),
            "quality": overall_quality,
            "unscored_reason": unscored_reason,
            "grade": grade,
            "applied_caps": applied_caps,
            "criteria": criteria_list,
        },
        "coverage": coverage,
        "hints": list(hints or []),
        "diagnostics": diagnostics_recent[-50:] if isinstance(diagnostics_recent, list) else [],
        "measurements": dict(canonical or {}),
    }

    # ---------------------------------------------------------------------
    # ✅ תוספת חשובה: שמירת בלוקי canonical + rep לדוחות
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
