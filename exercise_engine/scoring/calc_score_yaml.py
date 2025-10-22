# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# calc_score_yaml.py — חישוב ציון כללי מונחה-YAML (Generic)
#
# מה עושה:
# - קורא spec של כל קריטריון מתוך ex.raw["criteria"][<name>]["scoring"]
# - מחשב ציון 0..1 לכל קריטריון לפי type/פרמטרים
# - מבצע שקלול (vote) לציון כללי לפי weights מתוך ה-YAML (base/override)
#
# הערות:
# - אין כאן "דוחות". רק חישוב ציונים. הדו"ח יישאר בקובץ הדוחות שלך.
# - יש אליאס: score_criteria = calc_criteria (לשמור תאימות ל-runtime הקיים).
# - זמינות/חוסר זמינות נגזרת מ-"requires" שב-YAML. אם חסר → הקריטריון לא מנוקד.
# -----------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from exercise_engine.registry.loader import ExerciseDef

# אינדיקציות (לא חובה)
try:
    from exercise_engine.monitoring import diagnostics as diag
    _HAVE_DIAG = True
except Exception:
    _HAVE_DIAG = False

def _emit(ev_type: str, severity: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    if not _HAVE_DIAG:
        return
    try:
        diag.emit(ev_type, severity=severity, message=message, context=context or {})
    except Exception:
        pass

# ───────────────────────────── מודלים ─────────────────────────────

@dataclass
class CriterionScore:
    id: str
    available: bool
    score: Optional[float]
    reason: Optional[str] = None  # למשל "unavailable" / "missing_requires" / None

@dataclass
class VoteResult:
    overall: Optional[float]            # 0..1 או None אם אין מה לשקלל
    quality: Optional[str]              # "full" / "partial" / "poor"
    used_criteria: List[str] = field(default_factory=list)
    skipped_criteria: List[str] = field(default_factory=list)

# ─────────────────────────── עזר מתמטי ───────────────────────────

def _linmap(x: float, x0: float, x1: float, y0: float, y1: float) -> float:
    if x0 == x1:
        return y0
    t = (x - x0) / (x1 - x0)
    if t < 0: t = 0.0
    elif t > 1: t = 1.0
    return y0 + t * (y1 - y0)

def _get_float(canon: Dict[str, Any], key: str) -> Optional[float]:
    v = canon.get(key)
    try:
        return float(v) if v is not None else None
    except Exception:
        return None

def _all_present(canon: Dict[str, Any], keys: List[str]) -> bool:
    for k in keys:
        if canon.get(k) is None:
            return False
    return True

# ───────────────────── מחשבי ציון גנריים (לפי type) ─────────────────────
# הערה: mid_score ברירת מחדל 0.6 (לדרגת "warn"), ניתן לשנות ב-YAML לכל קריטריון.

def _score_smaller_better(val: float, good: float, bad: float,
                          warn: Optional[float], mid: float) -> float:
    if val <= good:
        return 1.0
    if warn is not None and val <= warn:
        return _linmap(val, good, warn, 1.0, mid)
    if val >= bad:
        return 0.0
    x0 = warn if warn is not None else good
    y0 = mid if warn is not None else 1.0
    return _linmap(val, x0, bad, y0, 0.0)

def _score_bigger_better(val: float, good: float, bad: float,
                          warn: Optional[float], mid: float) -> float:
    if val >= good:
        return 1.0
    if warn is not None and val >= warn:
        return _linmap(val, warn, good, mid, 1.0)
    if val <= bad:
        return 0.0
    x1 = warn if warn is not None else good
    y1 = mid if warn is not None else 1.0
    return _linmap(val, bad, x1, 0.0, y1)

def _score_in_range(val: float, min_ok: float, max_ok: float,
                    min_cutoff: float, max_cutoff: float) -> float:
    if min_ok <= val <= max_ok:
        return 1.0
    if val < min_ok:
        if val <= min_cutoff:
            return 0.0
        return _linmap(val, min_cutoff, min_ok, 0.0, 1.0)
    # val > max_ok
    if val >= max_cutoff:
        return 0.0
    return _linmap(val, max_ok, max_cutoff, 1.0, 0.0)

def _score_tempo_window(val: float, min_s: float, max_s: float,
                        min_cutoff: float, max_cutoff: float) -> float:
    if min_s <= val <= max_s:
        return 1.0
    if val < min_s:
        if val <= min_cutoff:
            return 0.0
        return _linmap(val, min_cutoff, min_s, 0.0, 1.0)
    if val >= max_cutoff:
        return 0.0
    return _linmap(val, max_s, max_cutoff, 1.0, 0.0)

# ───────────────────── חישוב קריטריון לפי spec ב-YAML ─────────────────────

def _score_by_spec(spec: Dict[str, Any], canon: Dict[str, Any]) -> Optional[float]:
    """
    spec.type נתמך:
      - smaller_better {key, good, [warn], bad, [mid_score]}
      - smaller_better_of_min {keys[], good, [warn], bad, [mid_score]}
      - abs_smaller_better_of_max {keys[], good, [warn], bad, [mid_score]}
      - bigger_better {key, good, [warn], bad, [mid_score]}
      - in_range {key, min_ok, max_ok, min_cutoff, max_cutoff}
      - tempo_window {key, min, max, min_cutoff, max_cutoff}
    """
    if not isinstance(spec, dict):
        return None
    t = spec.get("type")
    mid = float(spec.get("mid_score", 0.6))

    if t == "smaller_better":
        key = spec.get("key")
        v = _get_float(canon, key) if isinstance(key, str) else None
        if v is None: return None
        return _score_smaller_better(v, float(spec["good"]), float(spec["bad"]), spec.get("warn"), mid)

    if t == "smaller_better_of_min":
        keys = list(spec.get("keys") or [])
        if not keys: return None
        vals = [_get_float(canon, k) for k in keys]
        if any(v is None for v in vals): return None
        v = min(vals)
        return _score_smaller_better(v, float(spec["good"]), float(spec["bad"]), spec.get("warn"), mid)

    if t == "abs_smaller_better_of_max":
        keys = list(spec.get("keys") or [])
        if not keys: return None
        vals = [_get_float(canon, k) for k in keys]
        if any(v is None for v in vals): return None
        # max(|L|,|R|)
        try:
            v = max(abs(vals[0]), abs(vals[1] if len(vals) > 1 else vals[0]))
        except Exception:
            return None
        return _score_smaller_better(v, float(spec["good"]), float(spec["bad"]), spec.get("warn"), mid)

    if t == "bigger_better":
        key = spec.get("key")
        v = _get_float(canon, key) if isinstance(key, str) else None
        if v is None: return None
        return _score_bigger_better(v, float(spec["good"]), float(spec["bad"]), spec.get("warn"), mid)

    if t == "in_range":
        key = spec.get("key")
        v = _get_float(canon, key) if isinstance(key, str) else None
        if v is None: return None
        return _score_in_range(v, float(spec["min_ok"]), float(spec["max_ok"]),
                               float(spec["min_cutoff"]), float(spec["max_cutoff"]))

    if t == "tempo_window":
        key = spec.get("key")
        v = _get_float(canon, key) if isinstance(key, str) else None
        if v is None: return None
        return _score_tempo_window(v, float(spec["min"]), float(spec["max"]),
                                   float(spec["min_cutoff"]), float(spec["max_cutoff"]))

    # כאן ניתן להוסיף types נוספים בעתיד (למשל יחס בין שני מפתחות, בוליאני וכו')
    return None

# ───────────────────────── זמינות וציונים ─────────────────────────

def calc_criteria(*, exercise: ExerciseDef, canonical: Dict[str, Any],
                  availability: Dict[str, Dict[str, Any]]) -> Dict[str, CriterionScore]:
    """
    קלט:
      - exercise.raw["criteria"] ע"פ ה-YAML
      - canonical (אחרי normalizer)
      - availability: {"<criterion>": {"available": bool, "missing": [...], "reason": str}}
        * אם אין לך מודול ולידציה חיצוני — אפשר לבנות availability לפי requires כאן.
    פלט:
      - מפה {criterion -> CriterionScore}
    """
    out: Dict[str, CriterionScore] = {}

    for name, cdef in (exercise.raw.get("criteria") or {}).items():
        reqs = list((cdef or {}).get("requires") or [])
        avail = bool(availability.get(name, {}).get("available", False)) if isinstance(availability, dict) else _all_present(canonical, reqs)
        if not avail:
            out[name] = CriterionScore(id=name, available=False, score=None, reason="unavailable")
            _emit("criterion_unavailable", "warn", f"criterion '{name}' unavailable", {"exercise": exercise.id})
            continue

        spec = (cdef or {}).get("scoring") or {}
        s = _score_by_spec(spec, canonical)
        if s is None:
            out[name] = CriterionScore(id=name, available=True, score=None, reason="no_score_spec_or_missing_input")
            _emit("criterion_no_score", "warn", f"criterion '{name}' has no computed score", {"exercise": exercise.id})
            continue

        s = max(0.0, min(1.0, float(s)))
        out[name] = CriterionScore(id=name, available=True, score=s, reason=None)
        _emit("criterion_scored", "info", f"criterion '{name}' scored", {"exercise": exercise.id, "score": s})

    return out

# שמירה על תאימות לשם הישן בריצה (runtime ישן שקורא score_criteria)
score_criteria = calc_criteria

def vote(*, exercise: ExerciseDef, per_criterion: Dict[str, CriterionScore]) -> VoteResult:
    weights = exercise.weights or {}
    used: List[str] = []
    skipped: List[str] = []
    num = 0.0
    den = 0.0

    for name, cs in per_criterion.items():
        if cs.available and cs.score is not None:
            w = float(weights.get(name, 1.0))
            num += cs.score * w
            den += w
            used.append(name)
        else:
            skipped.append(name)

    if den == 0.0:
        _emit("vote_computed", "info", "vote skipped (no available criteria)", {"used": used, "skipped": skipped})
        return VoteResult(overall=None, quality="poor", used_criteria=used, skipped_criteria=skipped)

    overall = max(0.0, min(1.0, num / den))
    quality = "full" if len(used) >= 3 else "partial"
    _emit("vote_computed", "info", "vote computed", {"overall": overall, "used": used, "skipped": skipped})
    return VoteResult(overall=overall, quality=quality, used_criteria=used, skipped_criteria=skipped)
