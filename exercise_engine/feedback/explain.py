# -*- coding: utf-8 -*-
"""
explain.py — מחולל טיפים/הסברים גנרי לכל התרגילים (כולל טכני)
----------------------------------------------------------------
1) כל הטקסטים נמשכים מ-exercise_library/phrases.yaml (עברית).
2) יוצר טיפים לפי per_criterion_scores + canonical.
3) תומך בסיכום rep/set, וממלא placeholders כגון {{measured_deg}} וכו'.
4) משלב הודעות Camera Wizard + SetVisibilityAudit מה-phrases.yaml (ללא הצפה).

API:
- generate_rep_hints(exercise, canonical, per_criterion_scores, phrases_path=...)
- generate_set_hints(exercise, canonical, per_criterion_scores, camera_audit=None, phrases_path=...)
- render_camera_issue(issue_dict, phrases_path=...)  # שימושי בזמן אמת

תלויות: pyyaml
"""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import math
import re

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

DEFAULT_PHRASES_PATH = Path("exercise_library/phrases.yaml")

POSITIVE_MIN = 0.85
WEAK_MAX = 0.60

# ──────────────────────────────────────────────────────────────────────────────
# טיפוסי עזר
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CriterionScore:
    score: Optional[float] = None
    available: bool = False

class _ExerciseDefP:
    id: str
    family: str
    equipment: str
    display_name: Optional[str]
    thresholds: Dict[str, Dict[str, float]]
    weights: Dict[str, float]
    criteria: Dict[str, Dict[str, Any]]

# ──────────────────────────────────────────────────────────────────────────────
# קריאה ובחירת משפטים
# ──────────────────────────────────────────────────────────────────────────────

def _require_yaml():
    if yaml is None:
        raise RuntimeError("PyYAML לא מותקן. התקן: pip install pyyaml")

def _load_phrases(path: Path = DEFAULT_PHRASES_PATH) -> Dict[str, Any]:
    _require_yaml()
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    he = doc.get("he") or doc
    return he

def _pick_phrase(phrases: Dict[str, Any], section: str, key: str) -> Optional[str]:
    sec = phrases.get(section) or {}
    val = sec.get(key)
    return val if isinstance(val, str) else None

def _render(tpl: str, values: Dict[str, Any]) -> str:
    out = tpl
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _th(ex: _ExerciseDefP, sec: str, key: str, default: float) -> float:
    try:
        return float(((ex.thresholds or {}).get(sec) or {}).get(key, default))
    except Exception:
        return float(default)

def _fmt_deg(x: Optional[float]) -> Optional[str]:
    if x is None: return None
    try: return f"{float(x):.0f}"
    except Exception: return None

def _fmt_s(x: Optional[float]) -> Optional[str]:
    if x is None: return None
    try: return f"{float(x):.2f}"
    except Exception: return None

def _fmt_ratio(x: Optional[float]) -> Optional[str]:
    if x is None: return None
    try: return f"{float(x):.2f}"
    except Exception: return None

def _is_pos(score: Optional[float], pos_min: float = POSITIVE_MIN) -> bool:
    return score is not None and score >= pos_min

def _is_weak(score: Optional[float], weak_max: float = WEAK_MAX) -> bool:
    return score is not None and score < weak_max

# ──────────────────────────────────────────────────────────────────────────────
# מיפוי קריטריונים → מקטעי טקסט
# ──────────────────────────────────────────────────────────────────────────────

CRIT_TO_SECTION = {
    "range_of_motion": "range_of_motion",
    "rom": "range_of_motion",
    "tempo": "tempo",
    "tempo_control": "tempo_control",
    "posture": "posture",
    "stance_width": "stance_width",
    "knee_alignment": "knee_alignment",
    "toe_angle": "toe_angle",
    "foot_contact": "foot_contact",
    "heel_lift": "heel_lift",
    "balance": "balance",
    "weight_shift": "weight_shift",
    "head_position": "head_position",
    "flags": "flags",
}

# ──────────────────────────────────────────────────────────────────────────────
# מילוי ערכים רלוונטיים ל-placeholders
# ──────────────────────────────────────────────────────────────────────────────

def _collect_values_for_section(section: str, exercise: _ExerciseDefP, canonical: Dict[str, Any]) -> Dict[str, Any]:
    v: Dict[str, Any] = {}

    if section == "range_of_motion":
        measured = canonical.get("rep.rom")
        target = _th(exercise, "range_of_motion", "target_deg", canonical.get("rom_target_deg") or 0.0)
        v["measured_deg"] = _fmt_deg(measured)
        v["target_deg"] = _fmt_deg(target)

    elif section == "tempo":
        rep_t = canonical.get("rep.timing_s")
        min_s = _th(exercise, "tempo", "min_s", 0.7)
        max_s = _th(exercise, "tempo", "max_s", 2.5)
        v["rep_time_s"] = _fmt_s(rep_t)
        v["min_s"] = _fmt_s(min_s)
        v["max_s"] = _fmt_s(max_s)

    elif section == "tempo_control":
        v["ecc_s"] = _fmt_s(canonical.get("rep.ecc_s"))
        v["con_s"]  = _fmt_s(canonical.get("rep.con_s"))

    elif section == "posture":
        tf = canonical.get("torso_forward_deg")
        v["torso_forward_deg"] = _fmt_deg(tf)
        v["max_good_deg"] = _fmt_deg(_th(exercise, "posture", "max_good_deg", 15.0))

    elif section == "stance_width":
        r = canonical.get("features.stance_width_ratio")
        v["stance_ratio"] = _fmt_ratio(r)
        v["min_ok"] = _fmt_ratio(_th(exercise, "stance_width", "min_ok", 0.90))
        v["max_ok"] = _fmt_ratio(_th(exercise, "stance_width", "max_ok", 1.20))

    elif section == "knee_alignment":
        try:
            L = canonical.get("knee_foot_alignment_left_deg")
            R = canonical.get("knee_foot_alignment_right_deg")
            if L is None and R is None:
                m_eff = None
            else:
                Lf = abs(float(L) if L is not None else 0.0)
                Rf = abs(float(R) if R is not None else 0.0)
                m_eff = max(Lf, Rf)
        except Exception:
            m_eff = None
        v["valgus_deg"] = _fmt_deg(m_eff)

    elif section == "toe_angle":
        v["toe_angle_left_deg"]  = _fmt_deg(canonical.get("toe_angle_left_deg"))
        v["toe_angle_right_deg"] = _fmt_deg(canonical.get("toe_angle_right_deg"))

    elif section == "weight_shift":
        v["weight_shift_ratio"] = _fmt_ratio(canonical.get("weight_shift"))

    return {k: vv for k, vv in v.items() if vv is not None}

# ──────────────────────────────────────────────────────────────────────────────
# Camera Wizard & SetVisibilityAudit — מה-YAML בלבד
# ──────────────────────────────────────────────────────────────────────────────

_KV_RE = re.compile(r"\b([A-Za-z0-9_.]+)\s*=\s*([^\s,]+)")

def _parse_tips_to_dict(tips: Optional[str]) -> Dict[str, Any]:
    """
    ממיר מחרוזות בסגנון 'dt_ms=123, avg_visibility=0.42' למילון.
    """
    if not tips or not isinstance(tips, str):
        return {}
    kv = {}
    for m in _KV_RE.finditer(tips):
        k, v = m.group(1), m.group(2)
        # ניסיון להמיר למספר
        try:
            if "." in v:
                kv[k] = round(float(v), 2)
            else:
                kv[k] = int(v)
        except Exception:
            kv[k] = v
    return kv

def render_camera_issue(issue: Dict[str, Any],
                        phrases_path: Path = DEFAULT_PHRASES_PATH) -> Optional[str]:
    """
    ממיר אירוע יחיד של Camera Wizard למשפט מתוך he.camera_wizard.<code>.
    issue צפוי לכלול: code, severity, text(לא נשתמש), tips(אופציונלי כ'key=value').
    """
    phrases = _load_phrases(phrases_path)
    sec = phrases.get("camera_wizard") or {}
    code = (issue or {}).get("code")
    if not code or code not in sec:
        return None
    tpl = sec[code]
    values = _parse_tips_to_dict((issue or {}).get("tips"))
    return _render(tpl, values) if isinstance(tpl, str) else None

def _append_set_visibility_audit(hints: List[str],
                                 phrases: Dict[str, Any],
                                 camera_audit: Dict[str, Any]) -> None:
    """
    מוסיף הודעת איכות צילום מסוף סט על בסיס he.set_visibility_audit.*
    """
    sec = phrases.get("set_visibility_audit") or {}
    sev = (camera_audit or {}).get("severity")
    stats = (camera_audit or {}).get("stats") or {}
    msg_key = "ok"
    if sev == "MEDIUM":
        msg_key = "note_medium"
    elif sev == "HIGH":
        msg_key = "warn_high"
    base_msg = sec.get(msg_key)
    if isinstance(base_msg, str) and base_msg not in hints:
        hints.append(base_msg)

    # טיפים עדינים בהתאם לסטטיסטיקות
    tips_sec = sec.get("tips") or {}
    stats_hint = sec.get("stats_hint") or {}

    avg_vis = stats.get("avg_visibility")
    max_dt  = stats.get("max_dt_ms")
    person_ratio = stats.get("person_ratio")
    measured_frames = stats.get("vis_measured_frames", 0) + stats.get("conf_measured_frames", 0) + stats.get("dt_measured_frames", 0)

    # תנאי לדוגמא: נראות נמוכה
    if isinstance(avg_vis, (int, float)) and avg_vis < 0.60:
        tip = tips_sec.get("improve_lighting")
        if isinstance(tip, str): hints.append(tip)
        hint_tpl = stats_hint.get("visibility_avg")
        if isinstance(hint_tpl, str):
            hints.append(_render(hint_tpl, {"avg_visibility": round(float(avg_vis), 2)}))

    # dt גבוה במיוחד
    if isinstance(max_dt, (int, float)) and max_dt >= 1200.0:
        tip = tips_sec.get("reduce_load")
        if isinstance(tip, str): hints.append(tip)
        hint_tpl = stats_hint.get("max_dt")
        if isinstance(hint_tpl, str):
            hints.append(_render(hint_tpl, {"max_dt_ms": round(float(max_dt), 0)}))

    # מעט נתונים → הצעה לעוד חזרות
    if isinstance(measured_frames, int) and measured_frames < 30:
        tip = tips_sec.get("more_frames")
        if isinstance(tip, str): hints.append(tip)

    # יחס נוכחות אדם (מידעוני)
    if isinstance(person_ratio, (int, float)):
        hint_tpl = stats_hint.get("person_ratio")
        if isinstance(hint_tpl, str):
            hints.append(_render(hint_tpl, {"person_ratio": round(float(person_ratio), 2)}))

# ──────────────────────────────────────────────────────────────────────────────
# יצירת טיפים: חזרה / סט
# ──────────────────────────────────────────────────────────────────────────────

def _make_hints(*,
                mode: str,  # "rep" | "set"
                exercise: _ExerciseDefP,
                canonical: Dict[str, Any],
                per_criterion_scores: Dict[str, Any],
                phrases: Dict[str, Any]) -> List[str]:

    improve: List[Tuple[float, str]] = []
    good: List[Tuple[float, str]] = []

    for crit_name, score_obj in (per_criterion_scores or {}).items():
        section = CRIT_TO_SECTION.get(crit_name)
        if not section:
            continue

        s = getattr(score_obj, "score", None)
        avail = bool(getattr(score_obj, "available", False))

        if not avail or s is None:
            key = f"{mode}_missing"
        elif _is_weak(s):
            key = f"{mode}_weak"
        elif _is_pos(s):
            key = f"{mode}_good"
        else:
            continue

        tpl = _pick_phrase(phrases, section, key)
        if not tpl:
            continue

        values = _collect_values_for_section(section, exercise, canonical)
        text = _render(tpl, values)

        if key.endswith("_weak"):
            prior = 0.1 + (s if s is not None else 1.0)
            improve.append((prior, text))
        elif key.endswith("_missing"):
            prior = 0.05
            improve.append((prior, text))
        else:  # good
            prior = -(s if s is not None else 0.0)
            good.append((prior, text))

    improve.sort(key=lambda x: x[0])
    good.sort(key=lambda x: x[0])

    seen = set()
    ordered_texts: List[str] = []
    for _, t in improve + good:
        if t not in seen:
            ordered_texts.append(t)
            seen.add(t)
    return ordered_texts

# ──────────────────────────────────────────────────────────────────────────────
# API חיצוני
# ──────────────────────────────────────────────────────────────────────────────

def generate_rep_hints(*,
                       exercise: _ExerciseDefP,
                       canonical: Dict[str, Any],
                       per_criterion_scores: Dict[str, Any],
                       phrases_path: Path = DEFAULT_PHRASES_PATH) -> List[str]:
    phrases = _load_phrases(phrases_path)
    return _make_hints(mode="rep",
                       exercise=exercise,
                       canonical=canonical,
                       per_criterion_scores=per_criterion_scores,
                       phrases=phrases)

def generate_set_hints(*,
                       exercise: _ExerciseDefP,
                       canonical: Dict[str, Any],
                       per_criterion_scores: Dict[str, Any],
                       camera_audit: Optional[Dict[str, Any]] = None,
                       phrases_path: Path = DEFAULT_PHRASES_PATH,
                       include_camera_notes: bool = True) -> List[str]:
    phrases = _load_phrases(phrases_path)
    hints = _make_hints(mode="set",
                        exercise=exercise,
                        canonical=canonical,
                        per_criterion_scores=per_criterion_scores,
                        phrases=phrases)

    # סיכום טכני מה-YAML בלבד
    if include_camera_notes and camera_audit:
        try:
            _append_set_visibility_audit(hints, phrases, camera_audit)
        except Exception:
            pass

    return hints

def generate_hints(*,
                   exercise: _ExerciseDefP,
                   canonical: Dict[str, Any],
                   per_criterion_scores: Dict[str, Any]) -> List[str]:
    return generate_set_hints(exercise=exercise,
                              canonical=canonical,
                              per_criterion_scores=per_criterion_scores)
