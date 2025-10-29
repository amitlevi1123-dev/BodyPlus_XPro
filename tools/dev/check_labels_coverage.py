# -*- coding: utf-8 -*-
"""
בודק:
1) שכל canonical_keys ב-aliases.yaml מכוסים ב-metrics_labels.yaml/labels
2) שכל exercise/family/equipment שמופיעים בתרגילים קיימים ב-exercise_names.yaml
"""
from __future__ import annotations
from pathlib import Path
import yaml, sys

ALIASES = Path("exercise_library/aliases.yaml")
METRICS = Path("exercise_engine/report/metrics_labels.yaml")
NAMES   = Path("exercise_engine/report/exercise_names.yaml")
EX_DIR  = Path("exercise_library/exercises")

def yload(p: Path):
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}

def main():
    aliases = yload(ALIASES)
    metrics = yload(METRICS)
    names   = yload(NAMES)

    canon = set((aliases.get("canonical_keys") or {}).keys())
    label_keys = set(((metrics.get("labels") or {}) or {}).keys())

    missing_metric_labels = sorted(canon - label_keys)

    # אסוף ids/families/equipment אמיתיים
    ex_ids, fams, eqs = set(), set(), set()
    for y in EX_DIR.rglob("*.yaml"):
        doc = yload(y)
        if not isinstance(doc, dict):
            continue
        ex_id = doc.get("id")
        if ex_id: ex_ids.add(ex_id)
        fam = doc.get("family") or (doc.get("meta") or {}).get("family")
        if fam: fams.add(fam)
        eq  = doc.get("equipment") or (doc.get("meta") or {}).get("equipment")
        if eq: eqs.add(eq)

    nm = (names.get("names") or {})
    nm_ex = set((nm.get("exercises") or {}).keys())
    nm_fam= set((nm.get("families") or {}).keys())
    nm_eq = set((nm.get("equipment") or {}).keys())

    missing_ex = sorted(ex_ids - nm_ex)
    missing_fam = sorted(fams - nm_fam)
    missing_eq  = sorted(eqs - nm_eq)

    ok = True
    if missing_metric_labels:
        ok = False
        print("❌ חסרים labels למדדים (metrics_labels.yaml):")
        for k in missing_metric_labels:
            print("   -", k)

    if missing_ex or missing_fam or missing_eq:
        ok = False
        print("❌ exercise_names.yaml חסר ערכים ל:")
        if missing_ex:
            print("   exercises:", ", ".join(missing_ex[:20]), ("..." if len(missing_ex)>20 else ""))
        if missing_fam:
            print("   families:", ", ".join(missing_fam[:20]), ("..." if len(missing_fam)>20 else ""))
        if missing_eq:
            print("   equipment:", ", ".join(missing_eq[:20]), ("..." if len(missing_eq)>20 else ""))

    if ok:
        print("✅ כיסוי מלא — נראה מצוין.")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
