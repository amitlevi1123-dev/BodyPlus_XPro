# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🧾 list_ui_names.py — סקריפט איתור חכם: תרגילים/משפחות/ציוד + רשימת מדדים
# -----------------------------------------------------------------------------
# מה חדש?
# • מנסה לטעון load_library מ-exercise_library/loader.py ע"י איתור קובץ ישיר.
# • אם לא נמצא/נכשל — Fallback: סורק את כל התיקייה exercise_library וקורא YAML ישירות.
# • מוציא YAML אחד למסך:
#     summary.counts + library_version (hash סיכומי)
#     exercises: [{id, display_name, family, equipment}]
#     families:  [...]
#     equipment: [...]
#     metrics:   [{key, unit}] מתוך aliases.yaml
#
# הרצה:
#   (.venv) PS> python exercise_engine/report/list_ui_names.py
# -----------------------------------------------------------------------------

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys, hashlib

# ---------- Locators ----------
HERE = Path(__file__).resolve().parent
# ננסה להגדיר ROOT של הפרויקט (BodyPlus_XPro)
# אם עומק התיקיות ישתנה — עדיין נאתר לפי “exercise_library”
CANDIDATE_ROOTS = [
    HERE,                   # .../exercise_engine/report
    HERE.parent,            # .../exercise_engine
    HERE.parent.parent,     # .../BodyPlus_XPro?
    HERE.parent.parent.parent,
    Path.cwd(),
]

def find_exercise_library_root() -> Path:
    for base in CANDIDATE_ROOTS:
        p = (base / "exercise_library")
        if p.exists() and p.is_dir():
            return p.resolve()
    # חפש לעומק (יקר מעט; עדיין סביר)
    for base in CANDIDATE_ROOTS:
        for p in base.rglob("exercise_library"):
            if p.is_dir():
                return p.resolve()
    raise RuntimeError("לא נמצא תיקיית exercise_library בפרויקט.")

def find_loader_py(lib_root: Path) -> Optional[Path]:
    # לרוב הקובץ נמצא ב: exercise_library/loader.py
    p = lib_root / "loader.py"
    return p if p.exists() else None

# ---------- YAML helpers ----------
try:
    import yaml  # type: ignore
except Exception:
    print("ERROR: חסר PyYAML. התקן: pip install pyyaml", file=sys.stderr)
    raise

def read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def safe_yaml(path: Path) -> Any:
    try:
        return read_yaml(path) or {}
    except Exception:
        return {}

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def version_hash(paths: List[Path]) -> str:
    parts: List[str] = []
    for p in sorted(set([pp.resolve() for pp in paths if pp.exists()])):
        try:
            parts.append(f"{p.as_posix()}::{sha256_file(p)}")
        except Exception:
            parts.append(f"{p.as_posix()}::NA")
    blob = "|".join(parts).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]

# ---------- Primary: try importing loader.load_library by file ----------
def try_load_library_via_loader(lib_root: Path):
    loader_py = find_loader_py(lib_root)
    if not loader_py:
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("exlib_loader", str(loader_py))
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules["exlib_loader"] = mod
        spec.loader.exec_module(mod)  # type: ignore
        load_library = getattr(mod, "load_library", None)
        if load_library is None:
            return None
        lib = load_library(lib_root)  # ← משתמש בפונקציה שלך
        return {
            "exercises": [{
                "id": getattr(ex, "id", None),
                "display_name": getattr(ex, "display_name", None) or getattr(ex, "id", None),
                "family": getattr(ex, "family", None),
                "equipment": getattr(ex, "equipment", None),
                "origin_path": getattr(ex, "origin_path", None),
            } for ex in getattr(lib, "exercises", [])],
            "version": getattr(lib, "version", "unknown"),
        }
    except Exception as e:
        # נמשיך לפולבק; אבל נדפיס אינדיקציה
        print(f"[fallback] לא הצלחתי לטעון loader.py ({e}). עובר לסריקה ישירה…", file=sys.stderr)
        return None

# ---------- Fallback: scan YAMLs directly ----------
def fallback_scan(lib_root: Path) -> Dict[str, Any]:
    exercises_dir = lib_root / "exercises"
    ex_rows: List[Dict[str, Any]] = []
    involved_files: List[Path] = []
    # אסוף כל YAML תחת exercises/
    for p in exercises_dir.rglob("*.yaml"):
        involved_files.append(p)
        try:
            doc = read_yaml(p)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        ex_id = (doc.get("id") or "").strip() if isinstance(doc.get("id"), str) else ""
        if not ex_id:
            continue
        # קח מידע בסיסי אם קיים
        display_name = None
        if isinstance(doc.get("display_name"), str):
            display_name = doc["display_name"]
        elif isinstance(doc.get("meta"), dict) and isinstance(doc["meta"].get("display_name"), str):
            display_name = doc["meta"]["display_name"]
        family = doc.get("family") if isinstance(doc.get("family"), str) else None
        equipment = None
        if isinstance(doc.get("equipment"), str):
            equipment = doc["equipment"]
        elif isinstance(doc.get("meta"), dict) and isinstance(doc["meta"].get("equipment"), str):
            equipment = doc["meta"]["equipment"]

        ex_rows.append({
            "id": ex_id,
            "display_name": display_name or ex_id,
            "family": family,
            "equipment": equipment,
            "origin_path": p.as_posix(),
        })

    # גרסת ספרייה: hash של aliases/phrases וכל קבצי exercises שנקראו
    aliases = lib_root / "aliases.yaml"
    phrases = lib_root / "phrases.yaml"
    version = version_hash([aliases, phrases] + involved_files)

    return {
        "exercises": sorted(ex_rows, key=lambda r: r["id"]),
        "version": version,
    }

# ---------- Metrics from aliases.yaml ----------
def collect_metrics(lib_root: Path) -> List[Dict[str, Any]]:
    aliases = safe_yaml(lib_root / "aliases.yaml")
    canon = aliases.get("canonical_keys") if isinstance(aliases, dict) else {}
    rows: List[Dict[str, Any]] = []
    if isinstance(canon, dict):
        for key in sorted(canon.keys()):
            spec = canon.get(key) or {}
            unit = spec.get("unit") if isinstance(spec, dict) else None
            rows.append({"key": key, "unit": unit})
    return rows

def main() -> None:
    lib_root = find_exercise_library_root()

    data = try_load_library_via_loader(lib_root)
    if data is None:
        data = fallback_scan(lib_root)

    exercises = data.get("exercises", [])
    families = sorted({r["family"] for r in exercises if r.get("family")})
    equipment = sorted({r["equipment"] for r in exercises if r.get("equipment")})
    metrics = collect_metrics(lib_root)

    out = {
        "summary": {
            "counts": {
                "exercises": len(exercises),
                "families": len(families),
                "equipment": len(equipment),
                "metrics": len(metrics),
            },
            "library_version": data.get("version", "unknown"),
            "lib_root": lib_root.as_posix(),
        },
        "exercises": exercises,
        "families": families,
        "equipment": equipment,
        "metrics": metrics,
    }

    print(yaml.safe_dump(out, allow_unicode=True, sort_keys=False))

if __name__ == "__main__":
    main()
