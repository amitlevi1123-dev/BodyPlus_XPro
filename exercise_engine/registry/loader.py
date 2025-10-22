# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# loader.py — טוען את ספריית התרגילים (aliases / phrases / exercises/*.yaml)
# -----------------------------------------------------------------------------
# מה הקובץ עושה?
# 1) קורא aliases.yaml ו-phrases.yaml
# 2) קורא את כל קבצי exercises/*.yaml
# 3) מבצע מיזוג ירושה לפי extends: child <- parent (שרשרת מותרת)
# 4) עושה בדיקות בסיסיות (ID/criteria/critical)
# 5) בונה אובייקטי ExerciseDef עשירים בשדות שהמנוע צריך:
#    - meta, match_hints, selectable, origin_path
#    - criteria, thresholds, weights (כולל weights_override)
# 6) בונה אובייקט Library עם אינדקסים לפי id/משפחה וגרסת hash לספרייה
#
# הערות:
# • אין תלות במנוע הראשי; רק PyYAML לקריאת קבצים.
# • אם תרצה, אפשר להריץ את הקובץ כ-CLI לבדיקת עשן.
# -----------------------------------------------------------------------------

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# נסה לטעון PyYAML; אם לא קיים – נזרוק הודעה ברורה בהרצה
try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

LIB_DEFAULT_ROOT = Path("exercise_library")
ALIASES_FILE = "aliases.yaml"
PHRASES_FILE = "phrases.yaml"
EXERCISES_DIR = Path("exercises")

# ------------------------------- Models ---------------------------------------

@dataclass
class ExerciseDef:
    """
    ייצוג תרגיל לאחר מיזוג ירושה.
    שדות חשובים למסווג/מנוע:
    - meta: כל בלוק המטא מה-YAML (כולל meta.selectable אם קיים)
    - match_hints: רמזי התאמה למסווג (must_have/ranges/pose_view/weight)
    - selectable: דגל בר-בחירה (יכול להגיע מהטופ-לבל או מ-meta.selectable)
    - origin_path: נתיב קובץ המקור לצורך דיאגנוסטיקה
    """
    id: str
    raw: Dict[str, Any]                       # ה-YAML לאחר מיזוג "extends"
    family: Optional[str] = None
    equipment: Optional[str] = None
    display_name: Optional[str] = None
    criteria: Dict[str, Any] = field(default_factory=dict)
    critical: List[str] = field(default_factory=list)
    thresholds: Dict[str, Any] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)
    origin_file: Optional[Path] = None

    # ✨ החדשים/המורחבים:
    meta: Dict[str, Any] = field(default_factory=dict)
    match_hints: Dict[str, Any] = field(default_factory=dict)
    selectable: Optional[bool] = None
    origin_path: Optional[str] = None

@dataclass
class Library:
    """ספרייה טעונה: אליאסים, משפטים, תרגילים, אינדקסים, וגרסה."""
    root: Path
    aliases: Dict[str, Any]
    phrases: Dict[str, Any]
    exercises: List[ExerciseDef]
    index_by_id: Dict[str, ExerciseDef]
    index_by_family: Dict[str, List[ExerciseDef]]
    version: str
    files_fingerprint: Dict[str, str]   # מפה: path->sha256

# ------------------------------ YAML utils ------------------------------------

def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError(
            "PyYAML לא מותקן. התקן באמצעות: pip install pyyaml "
            "או ספק Loader חיצוני."
        )

def _load_yaml(path: Path) -> Any:
    _require_yaml()
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _deep_merge(base: Dict[str, Any], ext: Dict[str, Any]) -> Dict[str, Any]:
    """מיזוג עומק פשוט: dict בתוך dict; רשימות מוחלפות; טיפוסים אחרים – ext גובר."""
    out = dict(base)
    for k, v in ext.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore
        else:
            out[k] = v
    return out

# ------------------------------ Loaders ---------------------------------------

def _collect_exercise_files(root: Path) -> List[Path]:
    exercises_root = (root / EXERCISES_DIR)
    if not exercises_root.exists():
        return []
    return sorted([p for p in exercises_root.rglob("*.yaml") if p.is_file()])

def _build_version_hash(paths: List[Path]) -> Tuple[str, Dict[str, str]]:
    """יוצר גרסה דטרמיניסטית המבוססת על sha256 של כל קובץ בספרייה."""
    parts: List[str] = []
    fp: Dict[str, str] = {}
    for p in sorted(paths):
        digest = _sha256_file(p)
        parts.append(f"{p.as_posix()}::{digest}")
        fp[p.as_posix()] = digest
    blob = "|".join(parts).encode("utf-8")
    overall = hashlib.sha256(blob).hexdigest()[:12]
    return overall, fp

def _resolve_extends_map(all_docs: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    מקבל מפה exercise_id -> doc (מהקבצים), מבצע מיזוג "extends" רק לפי מזהי תרגילים.
    צורה:  child: {extends: parent_id, ...}  → merge(parent, child)
    תומך בשרשרת ירושה (A<-B<-C) עם זיהוי לולאות בסיסי.
    """
    resolved: Dict[str, Dict[str, Any]] = {}
    visiting: set[str] = set()

    def resolve(id_: str) -> Dict[str, Any]:
        if id_ in resolved:
            return resolved[id_]
        if id_ in visiting:
            raise ValueError(f"Cycle detected in 'extends' for id={id_}")
        visiting.add(id_)
        doc = dict(all_docs.get(id_) or {})
        parent_id = doc.get("extends")
        if parent_id:
            parent_doc = resolve(parent_id)
            doc = _deep_merge(parent_doc, {k: v for k, v in doc.items() if k != "extends"})
        resolved[id_] = doc
        visiting.remove(id_)
        return doc

    for k in list(all_docs.keys()):
        resolve(k)
    return resolved

def _minimal_schema_checks(doc: Dict[str, Any], origin: Path) -> List[str]:
    """
    בדיקות בסיסיות (לא מחליף schema.py המתקדם):
    - id חובה
    - criteria dict (אם קיים)
    - critical ⊆ criteria.keys()
    """
    errs: List[str] = []
    if not isinstance(doc.get("id"), str) or not doc["id"].strip():
        errs.append("missing id")
    crit = doc.get("criteria")
    if crit is not None and not isinstance(crit, dict):
        errs.append("criteria must be a mapping")
    # בדיקת critical⊆criteria (אם מוגדרים)
    if isinstance(doc.get("critical"), list) and isinstance(doc.get("criteria"), dict):
        crit_keys = set(doc["criteria"].keys())
        for c in doc["critical"]:
            if c not in crit_keys:
                errs.append(f"critical '{c}' not defined in criteria (file={origin.name})")
    return errs

def _normalize_exercise(doc: Dict[str, Any], origin: Path) -> ExerciseDef:
    """
    יוצר ExerciseDef מובנה מתוך doc לאחר מיזוג, כולל:
    - קריטריונים/ספים/משקלים (כולל weights_override)
    - פרטי מטא + רמזי התאמה למסווג
    - דגל selectable גם ברמת top-level וגם מתוך meta.selectable
    - נתיב מקור origin_path
    """
    ex_id = str(doc.get("id")).strip()

    # בסיסים
    family = doc.get("family") or (doc.get("meta") or {}).get("family")
    equipment = doc.get("equipment") or (doc.get("meta") or {}).get("equipment")
    display_name = doc.get("display_name") or (doc.get("meta") or {}).get("display_name")

    # מטא ורמזים (מאפשר גם הגדרה תחת meta וגם בטופ-לבל)
    meta = dict(doc.get("meta") or {})
    match_hints = dict(doc.get("match_hints") or meta.get("match_hints") or {})

    # selectable: אם הוגדר בטופ-לבל הוא גובר; אחרת נמשוך מ-meta.selectable
    selectable_top = doc.get("selectable")
    selectable_meta = meta.get("selectable") if isinstance(meta, dict) else None
    selectable = selectable_top if isinstance(selectable_top, bool) else (selectable_meta if isinstance(selectable_meta, bool) else None)

    # criteria & weights
    criteria = dict(doc.get("criteria") or {})
    weights: Dict[str, float] = {}
    # משקל מתוך criteria[crit].weight
    for k, v in criteria.items():
        w = v.get("weight") if isinstance(v, dict) else None
        if isinstance(w, (int, float)):
            weights[k] = float(w)
    # override אופציונלי (גובר)
    if isinstance(doc.get("weights_override"), dict):
        for k, v in doc["weights_override"].items():
            try:
                weights[k] = float(v)
            except Exception:
                pass

    return ExerciseDef(
        id=ex_id,
        raw=doc,
        family=family,
        equipment=equipment,
        display_name=display_name,
        criteria=criteria,
        critical=list(doc.get("critical") or []),
        thresholds=dict(doc.get("thresholds") or {}),
        weights=weights,
        origin_file=origin,
        # ✨ הרחבות
        meta=meta,
        match_hints=match_hints,
        selectable=selectable,
        origin_path=origin.as_posix(),
    )

# ------------------------------- Public API -----------------------------------

def load_library(root: Path | str = LIB_DEFAULT_ROOT) -> Library:
    """
    טוען את ספריית התרגילים בשלמותה ומחזיר אובייקט Library.
    זורק RuntimeError עם פירוט במקרה תקלה (שימושי ל-Preflight/Reload).
    """
    root = Path(root).resolve()
    if not root.exists():
        raise RuntimeError(f"library root not found: {root}")

    # 1) טעינת aliases + phrases
    aliases_path = (root / ALIASES_FILE)
    phrases_path = (root / PHRASES_FILE)
    if not aliases_path.exists():
        raise RuntimeError(f"missing {ALIASES_FILE} at {root}")
    if not phrases_path.exists():
        raise RuntimeError(f"missing {PHRASES_FILE} at {root}")

    aliases = _load_yaml(aliases_path)
    phrases = _load_yaml(phrases_path)

    # 2) איסוף קבצי exercises
    ex_files = _collect_exercise_files(root)
    if not ex_files:
        raise RuntimeError(f"no exercise YAML files found under {root / EXERCISES_DIR}")

    # 3) קריאה ראשונית של כל קובץ → doc ו-id
    raw_docs_by_id: Dict[str, Dict[str, Any]] = {}
    for p in ex_files:
        doc = _load_yaml(p)
        if not isinstance(doc, dict):
            raise RuntimeError(f"invalid YAML (not a mapping): {p}")
        ex_id = doc.get("id")
        if not isinstance(ex_id, str) or not ex_id.strip():
            raise RuntimeError(f"exercise missing 'id': {p}")
        if ex_id in raw_docs_by_id:
            prev = raw_docs_by_id[ex_id].get("__origin__")
            raise RuntimeError(f"duplicate exercise id '{ex_id}' in {p} and {prev}")
        doc["__origin__"] = p.as_posix()
        raw_docs_by_id[ex_id] = doc

    # 4) מיזוג ירושה (extends לפי id)
    merged_docs = _resolve_extends_map(raw_docs_by_id)

    # 5) בדיקות בסיסיות ואינסטנציאציה
    exercises: List[ExerciseDef] = []
    for ex_id, doc in merged_docs.items():
        origin_path = Path((raw_docs_by_id.get(ex_id) or {}).get("__origin__", "unknown"))
        errs = _minimal_schema_checks(doc, origin_path)
        if errs:
            raise RuntimeError(f"schema errors in {origin_path.name}: {', '.join(errs)}")
        exercises.append(_normalize_exercise(doc, origin_path))

    # 6) בניית אינדקסים
    index_by_id: Dict[str, ExerciseDef] = {ex.id: ex for ex in exercises}
    index_by_family: Dict[str, List[ExerciseDef]] = {}
    for ex in exercises:
        fam = ex.family or "_"
        index_by_family.setdefault(fam, []).append(ex)

    # 7) גרסת ספרייה (hash של aliases/phrases/כל קבצי exercises)
    all_paths = [aliases_path, phrases_path] + ex_files
    version, fingerprints = _build_version_hash(all_paths)

    return Library(
        root=root,
        aliases=aliases,
        phrases=phrases,
        exercises=exercises,
        index_by_id=index_by_id,
        index_by_family=index_by_family,
        version=version,
        files_fingerprint=fingerprints,
    )

# ------------------------------- CLI helper -----------------------------------

if __name__ == "__main__":  # הרצת בדיקת עשן ידנית
    try:
        lib = load_library()
        print(json.dumps({
            "version": lib.version,
            "exercises": [e.id for e in lib.exercises],
            "families": list(lib.index_by_family.keys()),
        }, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[loader] ERROR: {e}")
        raise
