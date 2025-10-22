# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# schema.py — ולידציה עמוקה לספריית התרגילים (aliases / phrases / exercises)
# -----------------------------------------------------------------------------
# מטרות:
# 1) לעצור טעינה של ספרייה שבורה (שגיאות ברורות)
# 2) להתריע על אי-עקביות/חוסרים לא קריטיים (אזהרות)
# 3) לשמור את הסכמה פשוטה: לא נוגעים במנוע, רק מאמתים קלט
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Tuple, Optional
from dataclasses import dataclass

# יחידות מותרות ב-aliases.yaml (תואם למה שיש לך בפועל)
_ALLOWED_UNITS = {
    None, "deg", "deg_s", "deg_s2", "ratio", "s", "px", "ms", "count", "text", "bool"
}

@dataclass
class ValidationReport:
    errors: List[str]
    warnings: List[str]

    def ok(self) -> bool:
        return not self.errors

def _err(acc: List[str], msg: str, where: str) -> None:
    acc.append(f"{where}: {msg}")

def _warn(acc: List[str], msg: str, where: str) -> None:
    acc.append(f"{where}: {msg}")

# ------------------------------- Aliases --------------------------------------

def validate_aliases(aliases: Dict[str, Any]) -> ValidationReport:
    errors: List[str] = []
    warnings: List[str] = []
    where = "aliases.yaml"

    if not isinstance(aliases, dict):
        _err(errors, "file must be a mapping", where)
        return ValidationReport(errors, warnings)

    canon = aliases.get("canonical_keys")
    if not isinstance(canon, dict) or not canon:
        _err(errors, "missing or empty 'canonical_keys' mapping", where)
    else:
        seen_aliases: Dict[str, str] = {}  # alias -> canonical (לזיהוי כפילויות)
        for key, spec in canon.items():
            if not isinstance(key, str) or not key.strip():
                _err(errors, "empty canonical key name", where)
                continue
            if not isinstance(spec, dict):
                _err(errors, f"canonical key '{key}' must map to an object", where)
                continue
            al = spec.get("aliases", [])
            if not isinstance(al, list) or not all(isinstance(a, str) for a in al):
                _err(errors, f"'{key}.aliases' must be a string list", where)
            unit = spec.get("unit")
            if unit not in _ALLOWED_UNITS:
                _warn(warnings, f"'{key}.unit' '{unit}' is not a known unit", where)
            # בדיקת כפילויות alias בין מפתחות קנוניים שונים (אזהרה)
            for a in al or []:
                prev = seen_aliases.get(a)
                if prev and prev != key:
                    _warn(warnings, f"alias '{a}' is duplicated under '{prev}' and '{key}'", where)
                else:
                    seen_aliases[a] = key

    tols = aliases.get("tolerances", {})
    if not isinstance(tols, dict):
        _warn(warnings, "missing 'tolerances' mapping (deg/deg_s/deg_s2/ratio/s/px/ms/count/text/bool)", where)

    return ValidationReport(errors, warnings)

# ------------------------------- Phrases --------------------------------------

def validate_phrases(phrases: Dict[str, Any]) -> ValidationReport:
    errors: List[str] = []
    warnings: List[str] = []
    where = "phrases.yaml"

    if not isinstance(phrases, dict):
        _err(errors, "file must be a mapping", where)
        return ValidationReport(errors, warnings)

    # מינימום: שפות כ-root keys
    if not any(k in phrases for k in ("he", "en")):
        _warn(warnings, "no 'he' or 'en' sections found (still allowed)", where)

    # בדיקת טיפוסים בסיסית
    for lang, m in phrases.items():
        if not isinstance(m, dict):
            _warn(warnings, f"language '{lang}' is not a mapping", where)

    return ValidationReport(errors, warnings)

# ------------------------------- Exercises ------------------------------------

def _validate_match_hints(hints: Any, where: str, warnings: List[str], errors: List[str]) -> None:
    """
    match_hints:
      must_have: [str, ...]
      ranges: { key: [lo, hi], ... }
      pose_view: [str, ...]
      weight: number
    """
    if hints is None:
        return
    if not isinstance(hints, dict):
        _err(errors, "'match_hints' must be a mapping", where)
        return

    mh = hints
    # must_have
    if "must_have" in mh and not (isinstance(mh["must_have"], list) and all(isinstance(x, str) for x in mh["must_have"])):
        _err(errors, "'match_hints.must_have' must be a list of strings", where)
    # ranges
    if "ranges" in mh:
        if not isinstance(mh["ranges"], dict):
            _err(errors, "'match_hints.ranges' must be a mapping", where)
        else:
            for k, v in mh["ranges"].items():
                ok = (isinstance(v, (list, tuple)) and len(v) == 2)
                if ok:
                    try:
                        float(v[0]); float(v[1])
                    except Exception:
                        ok = False
                if not ok:
                    _err(errors, f"'match_hints.ranges.{k}' must be [lo, hi] numbers", where)
    # pose_view
    if "pose_view" in mh and not (isinstance(mh["pose_view"], list) and all(isinstance(x, str) for x in mh["pose_view"])):
        _err(errors, "'match_hints.pose_view' must be a list of strings", where)
    # weight
    if "weight" in mh:
        try:
            w = float(mh["weight"])
            if w <= 0:
                _warn(warnings, "'match_hints.weight' is non-positive (<=0) — will mute candidate", where)
        except Exception:
            _err(errors, "'match_hints.weight' must be numeric", where)

def validate_exercise_doc(doc: Dict[str, Any], origin_name: str) -> ValidationReport:
    errors: List[str] = []
    warnings: List[str] = []
    where = f"ex:{origin_name}"

    # id
    ex_id = doc.get("id")
    if not isinstance(ex_id, str) or not ex_id.strip():
        _err(errors, "missing 'id'", where)

    # family/equipment/display_name — לא חובה, אך אם יש – להיות מחרוזות
    for fld in ("family", "equipment", "display_name"):
        if fld in doc and not (isinstance(doc[fld], str) or doc[fld] is None):
            _err(errors, f"'{fld}' must be string or omitted", where)

    # meta (אם קיים)
    meta = doc.get("meta")
    if meta is not None and not isinstance(meta, dict):
        _err(errors, "'meta' must be a mapping", where)
    else:
        if isinstance(meta, dict) and "selectable" in meta and not isinstance(meta["selectable"], bool):
            _err(errors, "'meta.selectable' must be boolean", where)

    # selectable בטופ-לבל (אופציונלי)
    if "selectable" in doc and not isinstance(doc["selectable"], bool):
        _err(errors, "'selectable' must be boolean", where)

    # match_hints (בטופ-לבל או בתוך meta)
    mh = doc.get("match_hints") or (meta.get("match_hints") if isinstance(meta, dict) else None)
    _validate_match_hints(mh, where, warnings, errors)

    # criteria
    criteria = doc.get("criteria")
    if criteria is not None and not isinstance(criteria, dict):
        _err(errors, "'criteria' must be a mapping", where)
    crit_keys = set(criteria.keys()) if isinstance(criteria, dict) else set()

    # לכל criterion: requires (list[str]), weight (מספר ≥0), אפשר עוד שדות חופשיים
    for c_name, c_def in (criteria or {}).items():
        if not isinstance(c_def, dict):
            _err(errors, f"criterion '{c_name}' must be an object", where)
            continue
        req = c_def.get("requires")
        if req is not None:
            if not isinstance(req, list) or not all(isinstance(x, str) for x in req):
                _err(errors, f"criterion '{c_name}.requires' must be a list of strings", where)
        if "weight" in c_def:
            try:
                w = float(c_def["weight"])
                if w < 0:
                    _err(errors, f"criterion '{c_name}.weight' must be ≥ 0", where)
            except Exception:
                _err(errors, f"criterion '{c_name}.weight' must be numeric", where)

    # critical subset of criteria
    critical = doc.get("critical", [])
    if critical:
        if not isinstance(critical, list) or not all(isinstance(c, str) for c in critical):
            _err(errors, "'critical' must be a list of strings", where)
        else:
            for c in critical:
                if c not in crit_keys:
                    _err(errors, f"'critical' item '{c}' is not in 'criteria'", where)

    # weights_override (אם קיים)
    weights_override = doc.get("weights_override")
    if weights_override is not None:
        if not isinstance(weights_override, dict):
            _err(errors, "'weights_override' must be a mapping", where)
        else:
            for k, v in weights_override.items():
                try:
                    if float(v) < 0:
                        _err(errors, f"negative weight for '{k}'", where)
                except Exception:
                    _err(errors, f"non-numeric weight for '{k}'", where)

    # thresholds טיפוסית – אובייקט (בדיקת טיפוס בלבד; תוכן מפורט לשכבת ה"שופטים")
    thresholds = doc.get("thresholds")
    if thresholds is not None and not isinstance(thresholds, dict):
        _err(errors, "'thresholds' must be a mapping", where)

    return ValidationReport(errors, warnings)

def validate_exercises_all(ex_docs: List[Tuple[str, Dict[str, Any]]]) -> ValidationReport:
    """ex_docs: רשימת (origin_name, doc) לאחר מיזוג extends."""
    errors: List[str] = []
    warnings: List[str] = []
    seen_ids = set()

    for origin, doc in ex_docs:
        rep = validate_exercise_doc(doc, origin)
        errors.extend(rep.errors)
        warnings.extend(rep.warnings)
        ex_id = doc.get("id")
        if isinstance(ex_id, str):
            if ex_id in seen_ids:
                _err(errors, f"duplicate exercise id '{ex_id}'", origin)
            seen_ids.add(ex_id)

    return ValidationReport(errors, warnings)

# ------------------------------- Library all ----------------------------------

def validate_library(
    *,
    aliases: Dict[str, Any],
    phrases: Dict[str, Any],
    exercises_merged_by_id: Dict[str, Dict[str, Any]],
) -> ValidationReport:
    """
    ולידציה ספרייתית מאוחדת; מחזיר דו״ח שגיאות/אזהרות ידידותי.
    כולל cross-check מול aliases עבור requires/match_hints.must_have/ranges keys.
    """
    e: List[str] = []
    w: List[str] = []

    rep_a = validate_aliases(aliases)
    e.extend(rep_a.errors); w.extend(rep_a.warnings)

    rep_p = validate_phrases(phrases)
    e.extend(rep_p.errors); w.extend(rep_p.warnings)

    # exercises
    pairs = [(f"{k}", v) for k, v in exercises_merged_by_id.items()]
    rep_e = validate_exercises_all(pairs)
    e.extend(rep_e.errors); w.extend(rep_e.warnings)

    # ---- Cross-checks קלים מול aliases.canonical_keys ----
    canon_keys = set((aliases.get("canonical_keys") or {}).keys())

    missing_from_aliases_requires: List[str] = []
    missing_from_aliases_hints: List[str] = []

    for origin, doc in pairs:
        # criteria.requires
        for c_name, c_def in (doc.get("criteria") or {}).items():
            reqs = c_def.get("requires") or []
            for r in reqs:
                # מפתחות היררכיים (features.X / bar.Y / rep.timing_s) — מתירים; ה-Normalizer מטפל בהם.
                if "." not in r and r not in canon_keys:
                    missing_from_aliases_requires.append(r)

        # match_hints: must_have & ranges
        meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
        hints = doc.get("match_hints") or meta.get("match_hints")
        if isinstance(hints, dict):
            # must_have
            for k in (hints.get("must_have") or []):
                if isinstance(k, str) and "." not in k and k not in canon_keys:
                    missing_from_aliases_hints.append(k)
            # ranges
            if isinstance(hints.get("ranges"), dict):
                for k in hints["ranges"].keys():
                    if isinstance(k, str) and "." not in k and k not in canon_keys:
                        missing_from_aliases_hints.append(k)

    if missing_from_aliases_requires:
        _warn(w, f"some 'requires' keys have no alias entry: {sorted(set(missing_from_aliases_requires))}", "cross-check")

    if missing_from_aliases_hints:
        _warn(w, f"some 'match_hints' keys have no alias entry: {sorted(set(missing_from_aliases_hints))}", "cross-check")

    return ValidationReport(e, w)
