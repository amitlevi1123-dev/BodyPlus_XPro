# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# הסבר קצר (עברית):
# בודק זמינות קריטריונים לפי הגדרות התרגיל (YAML), מזהה חוסרים קריטיים,
# ומחליט האם החזרה/הפריים הם Unscored. משמש לפני שלב השיפוט/שקלול.
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional

try:
    from exercise_engine.monitoring import diagnostics as diag
    _HAVE_DIAG = True
except Exception:
    _HAVE_DIAG = False

from exercise_engine.registry.loader import ExerciseDef  # טיפוס נתונים של תרגיל

STD_REASONS = (
    "occluded", "side_angle", "out_of_frame", "low_pose_confidence",
    "no_bar_detected", "insufficient_frames", "not_provided"
)

def _emit(ev_type: str, severity: str, message: str, context: Optional[Dict[str, Any]] = None) -> None:
    if not _HAVE_DIAG:
        return
    try:
        diag.emit(ev_type, severity=severity, message=message, context=context or {})
    except Exception:
        pass

def _has_key(canon: Dict[str, Any], key: str) -> bool:
    # המנוע עובד עם מפה שטוחה; מפתחות היררכיים (features./bar./rep.) מוכנסים כמו שהם.
    return key in canon

def evaluate_availability(ex_def: ExerciseDef, canonical: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    crit_map = ex_def.criteria or {}

    for crit_name, crit_def in crit_map.items():
        req = list((crit_def or {}).get("requires") or [])
        missing: List[str] = [k for k in req if not _has_key(canonical, k)]
        avail = len(missing) == 0
        reason = None if avail else "not_provided"

        out[crit_name] = {
            "available": avail,
            "missing": missing,
            "reason": reason,
        }

        if not avail:
            _emit(
                "missing_required",
                severity="warn",
                message=f"criterion '{crit_name}' missing required keys",
                context={"exercise": ex_def.id, "criterion": crit_name, "missing": missing}
            )
    return out

def decide_unscored(ex_def: ExerciseDef, availability: Dict[str, Dict[str, Any]]) -> Tuple[bool, Optional[str], List[str]]:
    critical = list(ex_def.critical or [])
    missing_crit: List[str] = []
    for c in critical:
        ci = availability.get(c) or {}
        if not ci.get("available", False):
            missing_crit.append(c)

    if missing_crit:
        reason = f"missing_critical: {', '.join(missing_crit)}"
        _emit(
            "unscored_missing_critical",
            severity="error",
            message=reason,
            context={"exercise": ex_def.id, "missing_critical": list(missing_crit)}
        )
        return True, reason, missing_crit
    return False, None, []
