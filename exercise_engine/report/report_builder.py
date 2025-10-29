# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 📘 report_builder.py — בניית דוחות סופיים לממשק המשתמש (UI)
# -----------------------------------------------------------------------------
# נקודות עיקריות:
# • דו־לשוניות (he/en) לשמות תרגיל/משפחה/ציוד ולתוויות קריטרונים דרך aliases/labels.
# • "נמדד מול יעד" לכל קריטריון מתוך thresholds של התרגיל.
# • ביקורת חזרה (rep_critique) + ביקורת סט (set_critique) — ממקדות מוקדי שיפור.
# • שמירת תאימות לאחור: כל ההרחבות אופציונליות; המבנה ההיסטורי נשמר.
# • report_health חכם: OK/WARN/FAIL + issues[] (כבר קיים).
# • metrics_detail אוטומטי (כבר קיים) — שומרנו ומשפרים קלות.
# • NEW: שילוב report_name_labeler — תוויות יפות למדדים ושמות תרגיל/משפחה/ציוד.
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, cast
from collections import Counter
from datetime import datetime

# === NEW: name/labeling for report UI (ללא נרמול ערכים) ===
try:
    # נתיב: exercise_engine/report/report_name_labeler.py
    from exercise_engine.report.report_name_labeler import build_ui_names  # type: ignore
except Exception:
    build_ui_names = None  # fallback: נמשיך בלי מודול התוויות

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

def _now_iso_z() -> str:
    return datetime.utcnow().isoformat() + "Z"

# ---------------------------- Aliases / i18n ----------------------------

def _alias_label(aliases: Optional[Dict[str, Any]], key: str, lang: str) -> Tuple[str, Optional[str]]:
    """
    מחזיר (label, unit) עבור מפתח קנוני/תרגיל/משפחה/ציוד.
    חיפוש לפי:
      - exercise / family / equipment → names.*
      - criteria/measure keys         → labels.*
    """
    if not isinstance(aliases, dict):
        return key, None

    # 1) labels.* למדדים
    labels = aliases.get("labels") or {}
    if isinstance(labels, dict) and key in labels:
        d = labels.get(key) or {}
        lbl = d.get(lang) or d.get("he") or d.get("en") or key
        unit = d.get("unit")
        return str(lbl), (str(unit) if unit is not None else None)

    # 2) names.* לישות (תרגיל/משפחה/ציוד)
    names = aliases.get("names") or {}
    for group in ("exercises", "families", "equipment"):
        g = names.get(group) or {}
        if isinstance(g, dict) and key in g:
            d = g.get(key) or {}
            lbl = d.get(lang) or d.get("he") or d.get("en") or key
            return str(lbl), None

    return key, None

def _alias_name_triplet(aliases: Optional[Dict[str, Any]], exercise_id: Optional[str],
                        family: Optional[str], equipment: Optional[str], lang: str) -> Dict[str, Dict[str, str]]:
    """
    בונה בלוק ui.lang_labels עבור exercise/family/equipment בשתי השפות, עם fallback.
    """
    def _both(k: Optional[str]) -> Dict[str, str]:
        if not k:
            return {"he": "-", "en": "-"}
        he, _ = _alias_label(aliases, k, "he")
        en, _ = _alias_label(aliases, k, "en")
        return {"he": he, "en": en}

    return {
        "exercise": _both(exercise_id),
        "family": _both(family),
        "equipment": _both(equipment),
    }

# ---------------------------- Targets / Thresholds ----------------------------

def _format_target_phrase(th: Optional[Dict[str, Any]], unit: Optional[str], lang: str) -> str:
    """
    יוצר טקסט יעד (he/en) מתוך thresholds של הקריטריון.
    תומך במבנים:
      - {"min": x}           → "יעד ≥ x" / "Target ≥ x"
      - {"max": x}           → "יעד ≤ x" / "Target ≤ x"
      - {"min": x, "max": y} → "טווח x–y" / "Range x–y"
      - {"range": {"min": x, "max": y}} — דומה
    """
    if not isinstance(th, dict) or not th:
        return "—"
    def _fmt(v):
        if isinstance(v, (int, float)):
            return str(v) + (unit or "")
        return str(v)

    # normalize
    r = th.get("range") if isinstance(th.get("range"), dict) else th
    mn = r.get("min") if isinstance(r.get("min"), (int, float)) else None
    mx = r.get("max") if isinstance(r.get("max"), (int, float)) else None

    if mn is not None and mx is not None:
        return f"{'טווח' if lang=='he' else 'Range'} {_fmt(mn)}–{_fmt(mx)}"
    if mn is not None:
        return f"{'יעד ≥' if lang=='he' else 'Target ≥'} {_fmt(mn)}"
    if mx is not None:
        return f"{'יעד ≤' if lang=='he' else 'Target ≤'} {_fmt(mx)}"
    return "—"

def _criterion_target(exercise, crit_id: str) -> Optional[Dict[str, Any]]:
    th = getattr(exercise, "thresholds", None)
    if not isinstance(th, dict):
        return None
    v = th.get(crit_id)
    return v if isinstance(v, dict) else None

# ---------------------------- Notes (Heuristics / phrases) ----------------------------

def _default_note_for_score(crit_label: str, target_text: str, score_pct: Optional[int], lang: str) -> str:
    if score_pct is None:
        return "—"
    if score_pct >= 85:
        return "ביצוע נקי" if lang == "he" else "Clean execution"
    if score_pct >= 70:
        return f"אפשר לשפר {crit_label}" if lang == "he" else f"Could improve {crit_label}"
    # < 70
    if target_text and target_text != "—":
        return f"שפר {crit_label} ({target_text})" if lang == "he" else f"Improve {crit_label} ({target_text})"
    return f"שפר {crit_label}" if lang == "he" else f"Improve {crit_label}"

def _phrase_for_criterion(phrases: Optional[Dict[str, Any]], crit_id: str, quality: Optional[str], lang: str) -> Optional[str]:
    """
    תמיכה עתידית ב-phrases.yaml (אם תבחר להשתמש).
    """
    if not isinstance(phrases, dict):
        return None
    lang_map = phrases.get(lang) or {}
    crit_map = (lang_map.get("criteria") or {})
    d = crit_map.get(crit_id)
    if not isinstance(d, dict):
        return None
    if quality and quality in d:
        return str(d[quality])
    return d.get("default")

# ---------------------------- Safety Caps ----------------------------

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

# ---------------------------- Coverage / Health ----------------------------

def _compute_coverage(exercise, availability: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
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

# ---------------------------- Metrics Detail (מוחזק) ----------------------------

_ALWAYS_KEYS = [
    "rep.timing_s", "rep.ecc_s", "rep.con_s", "rep.pause_top_s", "rep.pause_bottom_s",
    "torso_forward_deg", "spine_flexion_deg", "spine_curvature_side_deg",
    "features.stance_width_ratio", "toe_angle_left_deg", "toe_angle_right_deg",
    "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
    "heels_grounded", "foot_contact_left", "foot_contact_right",
]

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
    out: List[str] = []
    crit = getattr(exercise, "criteria", {}) or {}
    if isinstance(crit, dict):
        for _cid, cdef in crit.items():
            req = (cdef or {}).get("requires")
            if isinstance(req, list):
                for k in req:
                    if isinstance(k, str):
                        out.append(k)
    out.extend(_ALWAYS_KEYS)
    seen = set()
    uniq: List[str] = []
    for k in out:
        if k not in seen:
            uniq.append(k); seen.add(k)
    return uniq

def _present_keys(canonical: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        if k in canonical:
            v = canonical.get(k)
            if v is not None:
                out[k] = v
    return out

def _extract_rep_series(rep_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(rep_tree, dict) or not rep_tree:
        return []
    timing = rep_tree.get("timing_s")
    ecc = rep_tree.get("ecc_s")
    con = rep_tree.get("con_s")
    ptop = rep_tree.get("pause_top_s")
    pbot = rep_tree.get("pause_bottom_s")
    rep_id = rep_tree.get("rep_id")

    def _is_scalar(x):
        return not isinstance(x, (list, dict))

    all_fields = [timing, ecc, con, ptop, pbot, rep_id]
    if any(f is not None for f in all_fields) and all((_is_scalar(f) or f is None) for f in all_fields):
        return [{
            "rep_id": rep_id if rep_id is not None else 1,
            "timing_s": timing, "ecc_s": ecc, "con_s": con,
            "pause_top_s": ptop, "pause_bottom_s": pbot,
        }]

    def _to_indexed_list(x):
        if isinstance(x, list):
            return list(enumerate(x, start=1))
        if isinstance(x, dict):
            try:
                items = sorted(x.items(), key=lambda kv: (str(kv[0])))
            except Exception:
                items = list(x.items())
            return [(int(k) if str(k).isdigit() else k, v) for k, v in items]
        if x is None:
            return []
        return [(1, x)]

    idx_fields = {
        "timing_s": _to_indexed_list(timing),
        "ecc_s": _to_indexed_list(ecc),
        "con_s": _to_indexed_list(con),
        "pause_top_s": _to_indexed_list(ptop),
        "pause_bottom_s": _to_indexed_list(pbot),
        "rep_id": _to_indexed_list(rep_id),
    }

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
    relevant_keys = _gather_required_keys(exercise)
    present_all = _present_keys(canonical, relevant_keys)

    grouped: Dict[str, Dict[str, Any]] = {}
    for gname, gkeys in _GROUPS.items():
        grouped[gname] = _present_keys(present_all, gkeys)

    grouped_keys_flat = set(k for lst in _GROUPS.values() for k in lst)
    other_keys = [k for k in present_all.keys() if k not in grouped_keys_flat]
    grouped["other"] = _present_keys(present_all, other_keys)

    rep_series: List[Dict[str, Any]] = []
    if isinstance(rep_tree, dict) and rep_tree:
        rep_series = _extract_rep_series(rep_tree)

    return {
        "groups": grouped,
        "rep_tempo_series": rep_series,
        "stats": {
            "keys_available": len(present_all),
            "groups_non_empty": {k: bool(v) for k, v in grouped.items()},
            "has_rep_series": bool(rep_series),
        },
    }

# ---------------------------- Rep / Set Critique ----------------------------

def _criterion_score_pct(per_criterion_scores: Optional[Dict[str, Any]], cid: str) -> Optional[int]:
    if not isinstance(per_criterion_scores, dict):
        return None
    obj = per_criterion_scores.get(cid)
    try:
        sc = float(getattr(obj, "score", None))
        return _to_pct(sc)
    except Exception:
        return None

def _rep_critique_rows(*, exercise, canonical: Dict[str, Any],
                       per_criterion_scores: Optional[Dict[str, Any]],
                       aliases: Optional[Dict[str, Any]],
                       lang: str) -> List[Dict[str, Any]]:
    """
    בונה שורה לכל קריטריון: id, name_he/en, unit, measured, target_he/en, score_pct, note_he/en.
    """
    out: List[Dict[str, Any]] = []
    crit_defs = getattr(exercise, "criteria", {}) or {}
    for cid in crit_defs.keys():
        label, unit = _alias_label(aliases, cid, lang)
        measured = canonical.get(cid)  # אם יש ערך להצגה (אחרת — None)
        th = _criterion_target(exercise, cid)
        target_text_lang = _format_target_phrase(th, unit, lang)
        target_text_alt  = _format_target_phrase(th, unit, "en" if lang=="he" else "he")

        pct = _criterion_score_pct(per_criterion_scores, cid)

        # הערת איכות (phrases → ברירת מחדל)
        note_lang = _default_note_for_score(label, target_text_lang, pct, lang)
        note_alt  = _default_note_for_score(label, target_text_alt,  pct, ("en" if lang=="he" else "he"))

        out.append({
            "id": cid,
            "name_he": _alias_label(aliases, cid, "he")[0],
            "name_en": _alias_label(aliases, cid, "en")[0],
            "unit": unit,
            "measured": measured,
            "target_he": target_text_lang if lang=="he" else target_text_alt,
            "target_en": target_text_alt  if lang=="he" else target_text_lang,
            "score_pct": pct,
            "note_he": note_lang if lang=="he" else note_alt,
            "note_en": note_alt  if lang=="he" else note_lang,
        })
    return out

def _set_critique_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"set_score_pct": None, "rep_count": None, "top_issues": [], "summary_he": "-", "summary_en": "-"}
    crit_scores = []
    for r in rows:
        if isinstance(r.get("score_pct"), int):
            crit_scores.append(r["score_pct"])
    set_score_pct = int(round(sum(crit_scores)/len(crit_scores))) if crit_scores else None

    sorted_rows = sorted([r for r in rows if isinstance(r.get("score_pct"), int)], key=lambda x: x["score_pct"])
    top = sorted_rows[:3] if sorted_rows else []

    top_issues = [{
        "id": t["id"],
        "name_he": t["name_he"],
        "name_en": t["name_en"],
        "worst_rep_pct": t["score_pct"],
        "avg_pct": t["score_pct"],
    } for t in top]

    if top:
        he_focus = ", ".join([t["name_he"] for t in top])
        en_focus = ", ".join([t["name_en"] for t in top])
        summary_he = f"מוקדי שיפור: {he_focus}"
        summary_en = f"Focus: {en_focus}"
    else:
        summary_he = "ביצוע נקי יחסית בסט זה."
        summary_en = "Relatively clean set."

    return {
        "set_score_pct": set_score_pct,
        "rep_count": None,
        "top_issues": top_issues,
        "summary_he": summary_he,
        "summary_en": summary_en,
    }

# ---------------------------- Builder ----------------------------

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
    # --- חדשים / אופציונליים ---
    display_lang: str = "he",
    aliases: Optional[Dict[str, Any]] = None,
    phrases: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    # caps
    applied_caps: List[Dict[str, Any]] = []
    final_score = overall_score
    if exercise and overall_score is not None and isinstance(per_criterion_scores, dict):
        final_score, applied_caps = _apply_safety_caps(exercise, overall_score, per_criterion_scores)

    # criteria rows + breakdown
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
        criteria_breakdown_pct[name] = item["score_pct"] if item["available"] else None

    coverage = _compute_coverage(exercise, availability)

    ui_ranges = {
        "color_bar": [
            {"label": "red",    "from_pct": 0,  "to_pct": 60},
            {"label": "orange", "from_pct": 60, "to_pct": 75},
            {"label": "green",  "from_pct": 75, "to_pct": 100},
        ]
    }

    quality_effective = overall_quality or ("partial" if final_score is not None else None)

    # exercise/meta
    ex_block = None
    if exercise is not None:
        ex_block = {
            "id": exercise.id,
            "family": getattr(exercise, "family", None),
            "equipment": getattr(exercise, "equipment", None),
            "display_name": getattr(exercise, "display_name", exercise.id),
        }

    # ui.lang_labels (he/en) — Fallback קודם כל לפי aliases המקומיים
    ui_lang_labels = _alias_name_triplet(
        aliases=aliases,
        exercise_id=(ex_block or {}).get("id"),
        family=(ex_block or {}).get("family"),
        equipment=(ex_block or {}).get("equipment"),
        lang=display_lang,
    )

    report: Dict[str, Any] = {
        "meta": {
            "generated_at": _now_iso_z(),
            "payload_version": str(payload_version),
            "library_version": str(library_version),
        },
        "display_lang": display_lang,
        "exercise": ex_block,
        "ui": {
            "lang_labels": ui_lang_labels
        },
        "ui_ranges": ui_ranges,
        "scoring": {
            "score": final_score,
            "score_pct": _to_pct(final_score),
            "quality": quality_effective,
            "unscored_reason": unscored_reason,
            "applied_caps": applied_caps,
            "criteria": criteria_list,
            "criteria_breakdown_pct": criteria_breakdown_pct,
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

    # sets / reps (optional passthrough)
    if isinstance(sets, list) and sets:
        report["sets"] = sets
    if isinstance(reps, list) and reps:
        report["reps"] = reps

    # metrics_detail
    try:
        report["metrics_detail"] = build_auto_metrics_detail(
            exercise=exercise,
            canonical=report.get("canonical", {}) or report.get("measurements", {}) or {},
            rep_tree=report.get("rep", None),
        )
    except Exception:
        report["metrics_detail"] = {"error": "build_failed"}

    # ---------- NEW: measured-vs-targets + critiques ----------
    try:
        rows = _rep_critique_rows(
            exercise=exercise,
            canonical=report.get("canonical", {}) or report.get("measurements", {}) or {},
            per_criterion_scores=per_criterion_scores,
            aliases=aliases,
            lang=display_lang,
        )
        report["rep_critique"] = [{
            "set_index": 1,
            "rep_index": 1,
            "criteria": rows,
            "summary_he": _set_critique_from_rows(rows).get("summary_he"),
            "summary_en": _set_critique_from_rows(rows).get("summary_en"),
        }]

        set_summary = _set_critique_from_rows(rows)
        report["set_critique"] = [{
            "set_index": 1,
            "set_score_pct": set_summary.get("set_score_pct"),
            "rep_count": set_summary.get("rep_count"),
            "top_issues": set_summary.get("top_issues"),
            "summary_he": set_summary.get("summary_he"),
            "summary_en": set_summary.get("summary_en"),
        }]
    except Exception:
        report["rep_critique"] = []
        report["set_critique"] = []

    # ---------- NEW: integrate report_name_labeler (labels & pretty metrics) ----------
    try:
        if build_ui_names is not None:
            # מעדיפים מפתחות קנוניים אם קיימים, אחרת measurements
            metrics_src = report.get("canonical", {}) or report.get("measurements", {}) or {}
            ex_id = (ex_block or {}).get("id")
            names_pack = build_ui_names(
                metrics_normalized=metrics_src,
                exercise_id=ex_id,
                aliases_yaml=aliases,   # לצורך יחידות/פורמט
                lang=display_lang,
            )

            # תוויות יפות למדדים — UI יוכל להציג value_fmt/label/unit
            report["metrics_ui"] = names_pack.get("metrics_ui", {})

            # תוויות יפות לשמות תרגיל/משפחה/ציוד — גובר על ה-fallback אם קיים
            ex_labels = (names_pack.get("exercise") or {}).get("ui_labels") or {}
            if ex_labels:
                report["ui"]["lang_labels"] = {
                    "exercise": ex_labels.get("exercise") or report["ui"]["lang_labels"]["exercise"],
                    "family":   ex_labels.get("family")   or report["ui"]["lang_labels"]["family"],
                    "equipment":ex_labels.get("equipment")or report["ui"]["lang_labels"]["equipment"],
                }
        else:
            # אם המודול לא קיים — ממשיכים בלי metrics_ui
            report["metrics_ui"] = {}
    except Exception:
        # לא מפילים דו"ח בגלל labeling
        report["metrics_ui"] = report.get("metrics_ui", {})

    # health
    report["report_health"] = _compute_report_health(report)

    return report

# ---------------- Camera Summary Attach ----------------

def _normalize_camera_summary(camera_summary: Optional[Dict[str, Any]]) -> Dict[str, Any]:
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
