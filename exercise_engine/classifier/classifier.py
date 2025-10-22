# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# מסווג תרגיל יציב עם היסטרזיס + דילוג בטוח על "קבצי בסיס" (selectable:false/_base/.base).
# תוספת: Strong Switch Override:
#   - אם הפער בין המועמד המוביל לשני ≥ STRONG_SWITCH_MARGIN:
#       • אפשר להחליף גם בזמן Freeze אם STRONG_SWITCH_BYPASS_FREEZE=True
#       • מסמן stability.strong_override=True (כדי שה-runtime ישקול לעקוף Grace)
#
# הקובץ משתמש ב-SETTINGS מתוך exercise_engine.runtime.engine_settings
# -----------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import time
import os

# הגדרות מנוע
from exercise_engine.runtime.engine_settings import SETTINGS

# אינדיקציות (לא חובה)
try:
    from exercise_engine.runtime import log as elog
    _HAVE_DIAG = True
except Exception:
    _HAVE_DIAG = False

def _emit(ev_type: str, severity: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    if not _HAVE_DIAG:
        return
    try:
        elog.emit(ev_type, severity, message, **(context or {}))
    except Exception:
        pass

# ----- טיפוסים -----

@dataclass
class Candidate:
    id: str
    score: float

@dataclass
class Stability:
    kept_previous: bool = False
    margin: float = 0.0
    freeze_active: bool = False
    last_switch_ms: Optional[int] = None
    strong_override: bool = False  # החלפה ודאית

@dataclass
class ClassifierState:
    prev_exercise_id: Optional[str] = None
    confidence_ema: float = 0.0
    low_conf_since_ms: Optional[int] = None
    last_switch_ms: Optional[int] = None

@dataclass
class PickResult:
    status: str  # "ok" | "no_candidate"
    exercise_id: Optional[str]
    family: Optional[str]
    equipment_inferred: str
    confidence: float
    reason: str
    stability: Stability
    candidates: List[Candidate] = field(default_factory=list)
    state: ClassifierState = field(default_factory=ClassifierState)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

# ----- עזרי מטא/נתיב -----

def _meta(ex) -> Dict[str, Any]:
    return getattr(ex, "meta", None) or {}

def _origin_path(ex) -> str:
    p = getattr(ex, "origin_path", "") or getattr(ex, "file_path", "") or ""
    if not isinstance(p, str):
        return ""
    return p

def _is_selectable(ex) -> bool:
    """
    כללי דילוג בטוחים:
    1) אם meta.selectable == False → לא בר-בחירה
    2) אם selectable == False בטופ-לבל → לא בר-בחירה
    3) אם הנתיב מכיל '_base' בתיקייה → לא בר-בחירה
    4) אם ה-ID מסתיים ב'.base' → לא בר-בחירה
    אחרת: בר-בחירה.
    """
    m = _meta(ex)
    if isinstance(m, dict) and m.get("selectable") is False:
        return False
    sel_top = getattr(ex, "selectable", None)
    if sel_top is False:
        return False
    path = _origin_path(ex)
    if path and ("{0}_base{0}".format(os.sep) in (os.sep + path + os.sep)):
        return False
    ex_id = getattr(ex, "id", "") or ""
    if isinstance(ex_id, str) and ex_id.endswith(".base"):
        return False
    return True

def _exercise_meta(ex) -> Tuple[str, str]:  # (family, equipment)
    fam = getattr(ex, "family", None) or _meta(ex).get("family")
    eq  = getattr(ex, "equipment", None) or _meta(ex).get("equipment")
    return fam or "unknown", eq or "none"

def _match_hints(ex) -> Dict[str, Any]:
    return getattr(ex, "match_hints", None) or _meta(ex).get("match_hints") or {}

def _criteria_requires_as_must_have(ex) -> List[str]:
    out: List[str] = []
    crit = getattr(ex, "criteria", None) or _meta(ex).get("criteria") or {}
    for _name, c in (crit or {}).items():
        req = (c or {}).get("requires") or []
        for k in req:
            if isinstance(k, str) and k not in out:
                out.append(k)
    return out

# ----- אינדוקציית ציוד -----

def _infer_equipment(canonical: Dict[str, Any]) -> str:
    for k in canonical.keys():
        if k.startswith("bar.") or k.startswith("objdet."):
            return "barbell"
    return "none"  # bodyweight/none

# ----- ניקוד מועמד -----

def _score_candidate(canonical: Dict[str, Any], ex) -> float:
    hints = _match_hints(ex)
    must_have: List[str] = list(hints.get("must_have") or []) or _criteria_requires_as_must_have(ex)
    ranges: Dict[str, List[float]] = hints.get("ranges") or {}
    pose_view: List[str] = hints.get("pose_view") or []
    weight: float = float(hints.get("weight", 1.0))

    score = 0.0
    total_w = 0.0

    for key in must_have:
        total_w += 1.0
        if key in canonical and canonical[key] is not None:
            score += 1.0

    for key, rng in ranges.items():
        total_w += 1.0
        try:
            lo, hi = float(rng[0]), float(rng[1])
            val = float(canonical.get(key))
            if lo <= val <= hi:
                score += 1.0
        except Exception:
            pass

    if pose_view:
        total_w += 1.0
        vm = canonical.get("view_mode") or canonical.get("view.mode") or canonical.get("view.primary")
        if isinstance(vm, str) and vm in pose_view:
            score += 1.0

    if total_w <= 0.0:
        return 0.0
    base = (score / total_w)
    return max(0.0, min(1.0, base * weight))

def _ema(prev: float, new: float, alpha: float) -> float:
    return (alpha * new) + ((1.0 - alpha) * prev)

# ----- בחירה -----

def pick(
    canonical: Dict[str, Any],
    library,
    prev_state: Optional[ClassifierState] = None,
    *,
    freeze_active: bool = False,
    fallback_bodyweight_id: Optional[str] = None
) -> PickResult:

    now_ms = int(time.time() * 1000)
    state = prev_state or ClassifierState()

    # ספים/דגלים מה-SETTINGS
    S_MIN_ACCEPT       = SETTINGS.classifier.S_MIN_ACCEPT
    H_MARGIN_KEEP      = SETTINGS.classifier.H_MARGIN_KEEP
    H_MARGIN_SWITCH    = SETTINGS.classifier.H_MARGIN_SWITCH
    CONF_EMA_ALPHA     = SETTINGS.classifier.CONF_EMA_ALPHA
    LOW_CONF_EPS       = SETTINGS.classifier.LOW_CONF_EPS
    LOW_CONF_T_SEC     = SETTINGS.classifier.LOW_CONF_T_SEC
    FREEZE_DURING_REP  = SETTINGS.classifier.FREEZE_DURING_REP
    STRONG_MARGIN      = SETTINGS.classifier.STRONG_SWITCH_MARGIN
    BYPASS_FREEZE      = SETTINGS.classifier.STRONG_SWITCH_BYPASS_FREEZE

    # 1) ציוד + מועמדים ברי-בחירה בלבד
    eq = _infer_equipment(canonical)
    exercises = getattr(library, "exercises", []) or []

    selectable_all = [ex for ex in exercises if _is_selectable(ex)]
    if not selectable_all:
        _emit("classifier_no_candidate", "warn", "no selectable exercises in library",
              {"library_size": len(exercises)})
        return PickResult(
            status="no_candidate",
            exercise_id=state.prev_exercise_id,
            family=None,
            equipment_inferred=eq,
            confidence=state.confidence_ema,
            reason="no_selectable_in_library",
            stability=Stability(kept_previous=bool(state.prev_exercise_id), margin=0.0,
                                freeze_active=freeze_active, last_switch_ms=state.last_switch_ms),
            candidates=[],
            state=state,
            diagnostics=[{"type": "classifier_no_candidate", "severity": "warn", "message": "no selectable in library"}]
        )

    filtered = [ex for ex in selectable_all if (_exercise_meta(ex)[1] or "none") == eq]
    pool = filtered if filtered else selectable_all

    candidates_calc: List[Candidate] = []
    for ex in pool:
        s = _score_candidate(canonical, ex)
        candidates_calc.append(Candidate(id=ex.id, score=float(s)))

    if not candidates_calc:
        _emit("classifier_no_candidate", "warn", "no selectable candidates after filtering", {"eq": eq})
        return PickResult(
            status="no_candidate",
            exercise_id=state.prev_exercise_id,
            family=None,
            equipment_inferred=eq,
            confidence=state.confidence_ema,
            reason="no_candidate",
            stability=Stability(kept_previous=bool(state.prev_exercise_id), margin=0.0,
                                freeze_active=freeze_active, last_switch_ms=state.last_switch_ms),
            candidates=[],
            state=state,
            diagnostics=[{"type": "classifier_no_candidate", "severity": "warn", "message": "no candidates"}]
        )

    # 2) דירוג + ספים
    candidates_calc.sort(key=lambda c: c.score, reverse=True)
    top1 = candidates_calc[0]
    top2 = candidates_calc[1] if len(candidates_calc) > 1 else Candidate(id="__none__", score=0.0)
    margin = float(top1.score - top2.score)

    if top1.score < S_MIN_ACCEPT:
        _emit("classifier_no_candidate", "warn", "top1 below accept threshold",
              {"top1": top1.id, "score": top1.score})
        picked_id = state.prev_exercise_id or fallback_bodyweight_id
        reason = "kept_prev" if state.prev_exercise_id else "fallback_bodyweight"
        if reason == "fallback_bodyweight":
            _emit("classifier_fallback_bodyweight", "info", "fallback to BW", {"fallback_id": picked_id})
        return PickResult(
            status="ok" if picked_id else "no_candidate",
            exercise_id=picked_id,
            family=None,
            equipment_inferred=eq,
            confidence=state.confidence_ema,
            reason=reason if picked_id else "no_candidate",
            stability=Stability(kept_previous=bool(state.prev_exercise_id), margin=margin,
                                freeze_active=freeze_active, last_switch_ms=state.last_switch_ms),
            candidates=candidates_calc,
            state=state,
            diagnostics=[]
        )

    # 3) היסטרזיס/Sticky + Strong Switch
    kept_prev = False
    picked_id = top1.id
    strong_override = False
    switch_happened_now = False  # NEW: נשתמש כדי להבטיח last_switch_ms

    if state.prev_exercise_id and top1.id != state.prev_exercise_id:
        # Strong override?
        if margin >= STRONG_MARGIN:
            if freeze_active and BYPASS_FREEZE:
                strong_override = True
                switch_happened_now = True
                state.last_switch_ms = now_ms
                _emit("classifier_strong_switch", "info", "override during freeze",
                      {"from": state.prev_exercise_id, "to": top1.id, "margin": margin})
            elif not freeze_active:
                strong_override = True
                switch_happened_now = True
                state.last_switch_ms = now_ms
                _emit("classifier_strong_switch", "info", "override (no freeze)",
                      {"from": state.prev_exercise_id, "to": top1.id, "margin": margin})

        if not strong_override:
            if FREEZE_DURING_REP and freeze_active:
                kept_prev = True
                picked_id = state.prev_exercise_id
                _emit("freeze_on_rep_window", "info", "kept previous due to freeze",
                      {"prev": state.prev_exercise_id})
            else:
                if margin < H_MARGIN_KEEP:
                    kept_prev = True
                    picked_id = state.prev_exercise_id
                    _emit("classifier_kept_previous", "info", "kept previous (margin small)",
                          {"margin": margin, "prev": state.prev_exercise_id, "next": top1.id})
                elif margin >= H_MARGIN_SWITCH:
                    switch_happened_now = True
                    state.last_switch_ms = now_ms
                    _emit("classifier_switched", "info", "switched exercise",
                          {"from": state.prev_exercise_id, "to": top1.id, "margin": margin})
                else:
                    kept_prev = True
                    picked_id = state.prev_exercise_id
                    _emit("classifier_kept_previous", "info", "kept previous (margin mid)",
                          {"margin": margin, "prev": state.prev_exercise_id, "next": top1.id})

    # 4) Confidence EMA + Low-confidence
    instant_conf = float(top1.score)
    state.confidence_ema = _ema(state.confidence_ema, instant_conf, SETTINGS.classifier.CONF_EMA_ALPHA)

    if state.confidence_ema < SETTINGS.classifier.LOW_CONF_EPS:
        state.low_conf_since_ms = state.low_conf_since_ms or now_ms
    else:
        state.low_conf_since_ms = None

    if state.low_conf_since_ms and (now_ms - state.low_conf_since_ms) >= int(SETTINGS.classifier.LOW_CONF_T_SEC * 1000):
        _emit("classifier_low_confidence", "warn", "confidence EMA low over time",
              {"ema": state.confidence_ema})

    # עדכון prev ובניית יציבות — נבטיח שה- Stability מחזיר last_switch_ms עדכני
    state.prev_exercise_id = picked_id
    reason = "kept_prev" if kept_prev else ("strong_override" if strong_override else "best_match_rules")

    stability = Stability(
        kept_previous=kept_prev,
        margin=margin,
        freeze_active=freeze_active,
        last_switch_ms=state.last_switch_ms if switch_happened_now else state.last_switch_ms,
        strong_override=strong_override
    )

    diag_list: List[Dict[str, Any]] = []
    if strong_override:
        diag_list.append({
            "type": "classifier_strong_switch",
            "severity": "info",
            "message": "strong override",
            "context": {"margin": margin, "last_switch_ms": state.last_switch_ms}
        })

    return PickResult(
        status="ok",
        exercise_id=picked_id,
        family=None,
        equipment_inferred=eq,
        confidence=state.confidence_ema,
        reason=reason,
        stability=stability,
        candidates=candidates_calc,
        state=state,
        diagnostics=diag_list
    )
