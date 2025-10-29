# -*- coding: utf-8 -*-
"""
יוצר/מעדכן skeleton ל-exercise_names.yaml מתוך exercise_library,
מבלי לדרוס תוויות שכבר קיימות.
"""
from __future__ import annotations
from pathlib import Path
import yaml

LIB = Path("exercise_library")
EX_DIR = LIB / "exercises"
OUT = Path("exercise_engine/report/exercise_names.yaml")

def load_yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}

def deep_get(d, path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def deep_set(d, path, value):
    cur = d
    for k in path[:-1]:
        cur = cur.setdefault(k, {})
    cur[path[-1]] = value

def main():
    # קיים
    current = load_yaml(OUT) or {}
    names = current.get("names") or {}
    ex_map = names.get("exercises") or {}
    fam_map = names.get("families") or {}
    eq_map  = names.get("equipment") or {}

    # אסוף תרגילים
    for y in sorted(EX_DIR.rglob("*.yaml")):
        doc = load_yaml(y) or {}
        ex_id = doc.get("id")
        if not ex_id:
            continue
        fam = doc.get("family") or (doc.get("meta") or {}).get("family")
        eq  = doc.get("equipment") or (doc.get("meta") or {}).get("equipment")

        # הוסף placeholders רק אם חסר
        if ex_id not in ex_map:
            ex_map[ex_id] = {"he": ex_id, "en": ex_id}
        if fam and fam not in fam_map:
            fam_map[fam] = {"he": fam, "en": fam}
        if eq and eq not in eq_map:
            eq_map[eq] = {"he": eq, "en": eq}

    out = {"names": {"exercises": ex_map, "families": fam_map, "equipment": eq_map}}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=True), encoding="utf-8")
    print(f"[OK] wrote {OUT.as_posix()}")

if __name__ == "__main__":
    main()
