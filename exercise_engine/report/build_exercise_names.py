# -*- coding: utf-8 -*-
# =============================================================================
# build_exercise_names.py — חילוץ אוטומטי של שמות תרגילים (he/en) לכל ה-IDs
# =============================================================================
from __future__ import annotations
import re, sys
from pathlib import Path
from typing import Dict, Any
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # BodyPlus_XPro
REPORT_DIR   = PROJECT_ROOT / "exercise_engine" / "report"
OUTPUT_YAML  = REPORT_DIR / "exercise_names.yaml"
sys.path.insert(0, str(PROJECT_ROOT))
from exercise_engine.loader import load_library  # type: ignore
try:
    import yaml
except Exception:
    print("[build_exercise_names] התקן PyYAML: pip install pyyaml")
    raise
def is_hebrew(text: str) -> bool:
    import re as _re
    return bool(_re.search(r"[\u0590-\u05FF]", text or ""))
def prettify_from_id(ex_id: str) -> str:
    parts = ex_id.split(".")
    if not parts:
        return ex_id
    first = parts[0].replace("_"," ").strip().title()
    rest  = [p.replace("_"," ").strip().title() for p in parts[1:]]
    if rest:
        return f"{first} — " + " ".join(f"({p})" if i>0 else p for i,p in enumerate(rest))
    return first
def safe_name_pair(display_name: str | None, fallback_from_id: str) -> Dict[str, str]:
    dn = (display_name or "").strip()
    if dn:
        if is_hebrew(dn):
            return {"he": dn, "en": fallback_from_id}
        else:
            return {"he": dn, "en": dn}
    return {"he": fallback_from_id, "en": fallback_from_id}
def pretty_token(token: str) -> str:
    return token.replace("_"," ").strip().title()
def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    lib = load_library()
    names: Dict[str, Any] = {"names": {"exercises": {}}}
    # exercises
    for ex in lib.exercises:
        ex_id = ex.id
        disp = ex.display_name
        if not disp and isinstance(ex.raw, dict):
            meta = ex.raw.get("meta") or {}
            if isinstance(meta, dict):
                disp = meta.get("display_name")
        fallback = prettify_from_id(ex_id)
        names["names"]["exercises"][ex_id] = safe_name_pair(str(disp) if disp else None, fallback)
    # families
    families: Dict[str, Dict[str, str]] = {}
    for fam in sorted(lib.index_by_family.keys()):
        pretty = pretty_token(fam)
        families[fam] = {"he": pretty, "en": pretty}
    if families:
        names["names"]["families"] = families
    # equipment
    equipments: Dict[str, Dict[str, str]] = {}
    for ex in lib.exercises:
        eq = (ex.equipment or "").strip()
        if eq and eq not in equipments:
            pretty = pretty_token(eq)
            equipments[eq] = {"he": pretty, "en": pretty}
    if equipments:
        names["names"]["equipment"] = equipments
    with OUTPUT_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(names, f, allow_unicode=True, sort_keys=True)
    print(f"[build_exercise_names] כתוב: {OUTPUT_YAML.as_posix()}")
    print(f"[build_exercise_names] תרגילים: {len(names['names']['exercises'])} | משפחות: {len(families)} | ציוד: {len(equipments)}")
if __name__ == "__main__":
    main()
