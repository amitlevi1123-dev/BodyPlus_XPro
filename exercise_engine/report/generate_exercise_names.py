# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🧩 generate_exercise_names.py — חילוץ אוטומטי של שמות תרגילים/משפחות/ציוד
# -----------------------------------------------------------------------------
# מה הקובץ עושה?
# 1) סורק את exercise_library/exercises/**/*.yaml ומחלץ: id, family, equipment, display_name
#    (גם כאשר הם מופיעים תחת meta.* כמו meta.id / meta.display_name).
# 2) בונה YAML תצוגה בשם exercise_names.yaml בפורמט:
#       names:
#         exercises: { <id>: {he: "...", en: "..."} }
#         families:  { <family>: {he: "...", en: "..."} }
#         equipment: { <equipment>: {he: "...", en: "..."} }
# 3) זיהוי שפה אוטומטי ל-display_name:
#       - אם המחרוזת בעברית → he=display_name, en=TitleCase(guess)
#       - אחרת → en=display_name, he=TitleCase(guess_he בסיסי)
# 4) מוסיף מילון ברירת־מחדל קצר לציוד נפוץ (barbell/dumbbell/kettlebell/…),
#    ואינו דורס שמות שכבר נמצאו מקבצי התרגילים.
#
# הפעלה:
#    (venv) > python exercise_engine/report/generate_exercise_names.py
#
# יציאה:
#    exercise_engine/report/exercise_names.yaml
#
# הערות:
# • אין תלות במנוע הראשי; צריך PyYAML בלבד.
# • לא נוגעים ב-aliases.yaml. זה קובץ תצוגה נפרד ל-UI/דוחות.
# -----------------------------------------------------------------------------

from __future__ import annotations
import sys, re, json
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:
    print("⚠️  PyYAML לא מותקן. התקן: pip install pyyaml")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # .../BodyPlus_XPro
LIB_ROOT = PROJECT_ROOT / "exercise_library"
EX_DIR = LIB_ROOT / "exercises"
OUT_PATH = Path(__file__).resolve().parent / "exercise_names.yaml"

HEB_RE = re.compile(r"[\u0590-\u05FF]")  # טווח עברית

def _is_hebrew(s: str) -> bool:
    return bool(HEB_RE.search(s or ""))

def _title_case_guess(token: str) -> str:
    # הופך id/token לפורמט תצוגה (en): "deadlift.barbell.conventional" → "Deadlift Barbell Conventional"
    token = token.replace("_", " ").replace(".", " ").replace("-", " ")
    token = re.sub(r"\s+", " ", token).strip()
    return " ".join(w[:1].upper() + w[1:] for w in token.split(" ") if w)

def _title_case_guess_he(token: str) -> str:
    # לא באמת תרגום; רק הצגה קצת נקייה לעברית אם אין לך תרגום אמיתי
    # לדוגמה: "deadlift barbell" → "Deadlift Barbell" (באותיות לטיניות; עדיף לשנות ידנית בהמשך)
    return _title_case_guess(token)

def _get(doc: Dict[str, Any], *keys, default=None):
    cur: Any = doc
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return default
    return cur

def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            return {}
        return data

def _safe_id(doc: Dict[str, Any]) -> Optional[str]:
    # תומך גם ב-meta.id וגם ב-id בטופ־לבל
    return _get(doc, "id") or _get(doc, "meta", "id")

def _safe_display(doc: Dict[str, Any]) -> Optional[str]:
    return _get(doc, "display_name") or _get(doc, "meta", "display_name")

def _safe_family(doc: Dict[str, Any]) -> Optional[str]:
    return _get(doc, "family") or _get(doc, "meta", "family")

def _safe_equipment(doc: Dict[str, Any]) -> Optional[str]:
    return _get(doc, "equipment") or _get(doc, "meta", "equipment")

def _merge_first(dst: Dict[str, Any], key: str, val: Dict[str, str]) -> None:
    # ממזג ערך רק אם לא קיים
    if key not in dst:
        dst[key] = val

def _default_equipment_map() -> Dict[str, Dict[str, str]]:
    # מילון ברירת־מחדל קצר לציוד נפוץ (ניתן להרחיב בקלות)
    return {
        "barbell":   {"he": "מוט",          "en": "Barbell"},
        "dumbbell":  {"he": "משקולת יד",    "en": "Dumbbell"},
        "kettlebell":{"he": "קטלבל",       "en": "Kettlebell"},
        "trapbar":   {"he": "טרפ־בר",       "en": "Trap Bar"},
        "bodyweight":{"he": "משקל גוף",     "en": "Bodyweight"},
        "band":      {"he": "גומייה",       "en": "Band"},
        "cable":     {"he": "כבל",          "en": "Cable"},
        "machine":   {"he": "מכשיר",        "en": "Machine"},
        "smith":     {"he": "סמית׳",        "en": "Smith Machine"},
        "plate":     {"he": "צלחת משקל",    "en": "Plate"},
    }

def main() -> int:
    if not EX_DIR.exists():
        print(f"❌ לא נמצאה תיקיית תרגילים: {EX_DIR}")
        return 2

    exercises: Dict[str, Dict[str, str]] = {}
    families:  Dict[str, Dict[str, str]] = {}
    equipment: Dict[str, Dict[str, str]] = _default_equipment_map()

    yaml_paths = sorted(EX_DIR.rglob("*.yaml"))

    collisions = []  # לאינפו: display_name שונים לאותו id
    seen_ids = {}

    for p in yaml_paths:
        try:
            doc = _load_yaml(p)
        except Exception as e:
            print(f"⚠️  כשל בקריאת YAML: {p.name}: {e}")
            continue

        ex_id = _safe_id(doc)
        if not isinstance(ex_id, str) or not ex_id.strip():
            continue
        ex_id = ex_id.strip()

        disp = _safe_display(doc)
        fam  = _safe_family(doc)
        eq   = _safe_equipment(doc)

        # שמות תרגיל (exercises)
        if isinstance(disp, str) and disp.strip():
            if _is_hebrew(disp):
                he = disp.strip()
                en = _title_case_guess(ex_id.split(".")[-1])  # ניחוש עדין
            else:
                en = disp.strip()
                he = _title_case_guess_he(ex_id.split(".")[-1])
        else:
            # אין display_name → ניחושים עדינים משם ה-id
            base = ex_id.split(".")[-1]
            en = _title_case_guess(base)
            he = _title_case_guess_he(base)

        prev = seen_ids.get(ex_id)
        if prev and prev != disp and disp:
            collisions.append({"id": ex_id, "was": prev, "now": disp, "file": p.as_posix()})
        if disp:
            seen_ids[ex_id] = disp

        _merge_first(exercises, ex_id, {"he": he, "en": en})

        # שמות משפחה (families)
        if isinstance(fam, str) and fam.strip():
            fam_key = fam.strip()
            # נסה לגזור שם ממשהו עברי: אם מצאנו תרגיל בעברית באותה משפחה ניקח ממנו
            fam_he = None
            if _is_hebrew(he):
                fam_he = he  # עדיף שתעדכן ידנית אחר כך; זו רק התחלה
            _merge_first(families, fam_key, {
                "he": fam_he or _title_case_guess_he(fam_key),
                "en": _title_case_guess(fam_key),
            })

        # שמות ציוד (equipment)
        if isinstance(eq, str) and eq.strip():
            eq_key = eq.strip().lower()
            _merge_first(equipment, eq_key, {
                "he": _title_case_guess_he(eq_key),
                "en": _title_case_guess(eq_key),
            })

    # בניית מבנה ה־YAML
    out = {
        "names": {
            "exercises": exercises,
            "families": families,
            "equipment": equipment,
        },
        "_report": {
            "files_scanned": len(yaml_paths),
            "exercises_count": len(exercises),
            "families_count": len(families),
            "equipment_count": len(equipment),
            "display_name_collisions": collisions,  # אינפו בלבד; לא לשימוש ב־prod
        },
    }

    # כתיבה
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(out, f, allow_unicode=True, sort_keys=True)

    print(f"✅ נוצר: {OUT_PATH}")
    print(f"   תרגילים: {len(exercises)} | משפחות: {len(families)} | ציוד: {len(equipment)}")
    if collisions:
        print("ℹ️  נמצאו הבדלי display_name לאותו id (ראה _report.display_name_collisions בקובץ):")
        print(json.dumps(collisions[:5], ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
