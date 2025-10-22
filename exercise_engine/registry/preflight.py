# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# preflight.py — בדיקות Preflight לפני טעינת/ריענון ספריית תרגילים
# -----------------------------------------------------------------------------
# מה הוא עושה?
# 1) מפעיל ולידציה עמוקה (schema.validate_library) על aliases/phrases/exercises
# 2) מבצע בדיקות ייבשות (Dry Run) פשוטות אך שימושיות:
#    • לכל תרגיל יש לפחות criterion אחד
#    • סכום משקלים > 0 (אם הוגדרו משקלים)
#    • בדיקת ספי thresholds בסיסית (מספרים, לא NaN/inf)
#    • רמזים מול דגימות sample_payloads (אופציונלי) עבור requires/match_hints
# 3) מחזיר דו"ח ידידותי ל־UI/Reload (PreflightResult)
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from . import schema

@dataclass
class PreflightResult:
    ok: bool
    errors: List[str]
    warnings: List[str]
    notes: List[str]

# ----------------------------- עזרי איסוף/בדיקה ------------------------------

def _is_number(x: Any) -> bool:
    try:
        float(x)
        return True
    except Exception:
        return False

def _collect_requires(doc: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    מחזיר [(criterion_name, requires_key), ...]
    """
    out: List[Tuple[str, str]] = []
    for c_name, c_def in (doc.get("criteria") or {}).items():
        reqs = (c_def or {}).get("requires") or []
        for r in reqs:
            if isinstance(r, str):
                out.append((c_name, r))
    return out

def _collect_weights(doc: Dict[str, Any]) -> Dict[str, float]:
    """
    מאחד משקל מ-criteria[crit].weight + weights_override (אם קיים).
    """
    out: Dict[str, float] = {}
    for c_name, c_def in (doc.get("criteria") or {}).items():
        w = (c_def or {}).get("weight")
        try:
            if w is not None:
                out[c_name] = float(w)
        except Exception:
            pass
    for k, v in (doc.get("weights_override") or {}).items():
        try:
            out[k] = float(v)
        except Exception:
            pass
    return out

def _collect_match_hints(doc: Dict[str, Any]) -> Dict[str, Any]:
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    return (doc.get("match_hints") or meta.get("match_hints") or {}) if isinstance(meta, dict) or doc.get("match_hints") else {}

def _numbers_from_thresholds(th: Dict[str, Any]) -> List[float]:
    vals: List[float] = []
    for _, v in (th or {}).items():
        if isinstance(v, dict):
            for _, leaf in v.items():
                if _is_number(leaf):
                    vals.append(float(leaf))
        elif _is_number(v):
            vals.append(float(v))
    return vals

# --------------------------------- Main ---------------------------------------

def run_preflight(
    *,
    aliases: Dict[str, Any],
    phrases: Dict[str, Any],
    exercises_merged_by_id: Dict[str, Dict[str, Any]],
    sample_payloads: Optional[List[Dict[str, Any]]] = None,
) -> PreflightResult:
    errors: List[str] = []
    warnings: List[str] = []
    notes: List[str] = []

    # 1) ולידציה עמוקה (סכמה/היגיון בסיסי)
    rep = schema.validate_library(
        aliases=aliases,
        phrases=phrases,
        exercises_merged_by_id=exercises_merged_by_id,
    )
    errors.extend(rep.errors)
    warnings.extend(rep.warnings)

    # 2) בדיקות Dry-Run קלות על התרגילים
    for ex_id, doc in exercises_merged_by_id.items():
        # 2.1 יש לפחות criterion אחד
        crit = doc.get("criteria") or {}
        if not crit:
            errors.append(f"{ex_id}: exercise has no criteria defined")

        # 2.2 סכום משקלים > 0 (אם יש משקלים בכלל)
        weights = _collect_weights(doc)
        if weights:
            total_w = sum(max(0.0, float(w)) for w in weights.values())
            if total_w <= 0.0:
                errors.append(f"{ex_id}: total weights sum is <= 0 (check weights/weights_override)")

        # 2.3 thresholds – בדיקת ערכים מספריים תקינים (לא מחליף את השופטים)
        th = doc.get("thresholds") or {}
        nums = _numbers_from_thresholds(th)
        if any(not (x == x) for x in nums):  # NaN בדיקה
            errors.append(f"{ex_id}: thresholds contain NaN")
        if any(x in (float("inf"), float("-inf")) for x in nums):
            errors.append(f"{ex_id}: thresholds contain INF/-INF")

    # 3) רמזים מול דגימות (אופציונלי)
    #    הרעיון: לעזור למפתח לזהות מפתחות requires/hints שלא יופיעו בפועל בפרוד.
    if sample_payloads:
        sample_keys = set()
        for p in sample_payloads:
            if isinstance(p, dict):
                sample_keys.update(p.keys())

        missing_requires: List[str] = []
        missing_hints: List[str] = []

        for ex_id, doc in exercises_merged_by_id.items():
            # 3.1 requires
            for c_name, r in _collect_requires(doc):
                # אם זה מפתח היררכי (features./bar./rep./pose.) — נניח שה-Normalizer יטפל → לא מחייב הופעה בדגימות
                if "." in r:
                    continue
                if r not in sample_keys:
                    missing_requires.append(f"{ex_id}.{c_name}:{r}")

            # 3.2 match_hints
            mh = _collect_match_hints(doc)
            if isinstance(mh, dict):
                # must_have
                for k in (mh.get("must_have") or []):
                    if isinstance(k, str) and "." not in k and k not in sample_keys:
                        missing_hints.append(f"{ex_id}.match_hints.must_have:{k}")
                # ranges
                if isinstance(mh.get("ranges"), dict):
                    for k in mh["ranges"].keys():
                        if isinstance(k, str) and "." not in k and k not in sample_keys:
                            missing_hints.append(f"{ex_id}.match_hints.ranges:{k}")

        if missing_requires:
            warnings.append(
                "requires keys not seen in provided sample payloads: "
                + ", ".join(missing_requires[:30]) + (" ..." if len(missing_requires) > 30 else "")
            )

        if missing_hints:
            warnings.append(
                "match_hints keys not seen in provided sample payloads: "
                + ", ".join(missing_hints[:30]) + (" ..." if len(missing_hints) > 30 else "")
            )

    ok = not errors
    if ok:
        notes.append("preflight: library passed schema checks and dry-run")

    return PreflightResult(ok=ok, errors=errors, warnings=warnings, notes=notes)
