# -*- coding: utf-8 -*-
# =============================================================================
# 📘 report_name_labeler.py — מיפוי שמות ותוויות ל-UI (ללא נרמול ערכים!)
# =============================================================================
# מה הקובץ עושה?
# • מוסיף לדוחות שמות יפים (he/en) לתרגילים ולמדדים — לתצוגה ב-UI.
# • לא "מנרמל" ערכים ולא משנה אותם (בשונה מ-aliases.yaml שמנרמל מפתחות raw→canonical).
# • לא מבצע מיזוג/ממוצע בין מקורות שונים. כל הערכים נשארים כפי שהם.
#
# איך זה משתלב בפרויקט?
# 1) השכבה הטכנית (aliases.yaml / ה-Normalizer אצלך) כבר הפיקה dict של מדדים קנוניים
#    ו/או שאתה מעביר raw + aliases רק כדי שנזהה את שם המדד לצורך תווית — לא לשינוי ערכים.
# 2) הקובץ הזה לוקח:
#    - exercise_names.yaml  ← שמות תרגילים/משפחות/ציוד + אליאסים של מזהי תרגילים
#    - metrics_labels.yaml  ← שמות יפים למדדים קנוניים + רמזי פורמט
#    ומחזיר:
#    {
#      "exercise": { "id": <canonical or given>, "ui_labels": {...he/en...} },
#      "metrics_ui": { <key>: {label:{he,en}, unit,<value>,"value_fmt"} ... }
#    }
#
# הערות:
# • אם תעביר metrics_normalized — נציג תוויות ישירות לפי המפתחות הקנוניים.
# • אם תעביר raw_metrics + aliases_yaml — נזהה את שם המדד הקנוני רק לצורך תווית
#   (ללא שינוי הערך), כדי שתוכל להציג תווית גם כשעוד לא הרצית את מנגנון הנרמול שלך.
# • בחיים לא משנים ערכים כאן — רק נותנים להם שם ופורמט תצוגה.
# =============================================================================

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

import json

try:
    import yaml  # PyYAML
except Exception:
    yaml = None

# ---------- קבצי קונפיג לשמות ----------
ENGINE_DIR = Path(__file__).resolve().parent
NAMES_YAML = ENGINE_DIR / "exercise_names.yaml"
METRICS_YAML = ENGINE_DIR / "metrics_labels.yaml"


# ============================== עזרי טעינה ===================================

def _load_yaml(p: Path) -> Dict[str, Any]:
    if not yaml:
        raise RuntimeError("PyYAML לא מותקן. התקן: pip install pyyaml")
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ======================= מיפוי אליאסים של מפתחות (לשם בלבד) =================
# חשוב: זה *לא* מנרמל ערכים ולא מאחד התנגשות — רק מוצא את השם הקנוני
# כדי שנוכל לתת תווית. אם אין אליאס — נציג את המפתח כפי שהוא.

def _alias_maps_for_labels(aliases_yaml: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Any]]:
    alias_to_canon: Dict[str, str] = {}
    spec_by_canon: Dict[str, Any] = {}
    canon = (aliases_yaml or {}).get("canonical_keys") or {}
    for canon_key, spec in canon.items():
        spec_by_canon[canon_key] = spec or {}
        # canonical עצמו
        alias_to_canon[canon_key] = canon_key
        # וכל האליאסים שלו
        for a in (spec or {}).get("aliases", []) or []:
            alias_to_canon[str(a)] = canon_key
    return alias_to_canon, spec_by_canon


# =========================== שמות תרגילים (he/en) =============================

class ExerciseNames:
    def __init__(self, data: Dict[str, Any]):
        self.ex_db = (data or {}).get("exercises", {}) or {}
        self.aliases = (data or {}).get("aliases", {}) or {}

    def canonical_id(self, ex_id: Optional[str]) -> str:
        if not isinstance(ex_id, str) or not ex_id:
            return ""
        return self.aliases.get(ex_id, ex_id)

    def labels(self, ex_id: str) -> Dict[str, Any]:
        info = self.ex_db.get(ex_id) or {}
        labs = info.get("labels") or {}
        fam  = info.get("family") or {}
        eq   = info.get("equipment") or {}
        return {
            "exercise":  {"he": labs.get("he") or ex_id, "en": labs.get("en") or ex_id},
            "family":    {"he": fam.get("he")  or "",     "en": fam.get("en")  or ""},
            "equipment": {"he": eq.get("he")   or "",     "en": eq.get("en")   or ""},
        }


# ======================== תוויות מדדים + פורמט תצוגה =========================

class MetricLabels:
    def __init__(self, data: Dict[str, Any], spec_by_canon: Dict[str, Any]):
        self.labels = (data or {}).get("labels", {}) or {}
        self.hints  = (data or {}).get("format_hints", {}) or {}
        self.spec   = spec_by_canon  # מכיל unit מתוך aliases.yaml (אם הועבר)

    def _unit(self, key: str) -> Optional[str]:
        return (self.spec.get(key) or {}).get("unit")

    @staticmethod
    def _fmt_num(x: Any, digits: int) -> str:
        try:
            f = float(x)
            s = f"{f:.{digits}f}".rstrip("0").rstrip(".")
            return s
        except Exception:
            return str(x)

    def pretty_one(self, key: str, val: Any, lang: str = "he") -> Dict[str, Any]:
        # יחידה (אם ידועה מתוך aliases.yaml)
        unit = self._unit(key)
        # תווית יפה אם קיימת, אחרת המפתח עצמו
        lab  = self.labels.get(key) or {}
        label = {
            "he": lab.get("he") or key,
            "en": lab.get("en") or key,
        }

        # רמזי פורמט כלליים לפי סוג יחידה
        hint = self.hints.get(unit) or {}
        digits = int(hint.get("digits", 2))
        if unit == "bool":
            map_he = (hint.get("text_he") or {})
            map_en = (hint.get("text_en") or {})
            show = (map_he if lang == "he" else map_en)
            value_fmt = show.get(bool(val), "—")
        elif unit in ("deg", "s", "px", "ms", "ratio"):
            suffix = hint.get("suffix_he" if lang == "he" else "suffix_en", "")
            value_fmt = f"{self._fmt_num(val, digits)}{suffix}"
        else:
            # ללא יחידה ידועה — מציגים ערך גנרי
            value_fmt = str(val)

        return {
            "label": label,
            "unit": unit,
            "value": val,          # הערך המקורי, ללא שינוי
            "value_fmt": value_fmt # מחרוזת תצוגה בלבד
        }

    def pretty_map(self, metrics_by_key: Dict[str, Any], lang: str = "he") -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in (metrics_by_key or {}).items():
            out[k] = self.pretty_one(k, v, lang=lang)
        return out


# ================================ API ראשי ====================================

def build_ui_names(
    *,
    # אפשרות א': כבר יש לך מדדים קנוניים (מומלץ!) — נעשה להם תוויות בלבד:
    metrics_normalized: Optional[Dict[str, Any]] = None,
    # אפשרות ב': יש לך raw + aliases — נשתמש ב-aliases רק כדי לאתר את *שם* המפתח
    # הקנוני לצורך תווית. לא נוגעים בערך עצמו.
    raw_metrics: Optional[Dict[str, Any]] = None,
    aliases_yaml: Optional[Dict[str, Any]] = None,
    # תרגיל (מזהה עשוי להיות אליאס) — נמיר למזהה קנוני ונחזיר תוויות
    exercise_id: Optional[str] = None,
    lang: str = "he",
) -> Dict[str, Any]:
    """
    מחזיר מבנה מוכן לדוח:
    {
      "exercise": { "id": <canonical_id>, "ui_labels": {...} },
      "metrics_ui": { key: {label:{he,en}, unit, value, value_fmt}, ... }
    }

    • אם metrics_normalized ניתן — נשתמש בו ישירות (עדיף!).
    • אחרת, אם raw_metrics + aliases_yaml ניתנו — נאתר עבור כל מפתח raw את
      המפתח הקנוני לצורך תווית (הערך עצמו נשאר כפי שהוא).
    """
    # 1) תרגיל — מיפוי ל-ID קנוני + תוויות
    names = ExerciseNames(_load_yaml(NAMES_YAML))
    ex_id_canon = names.canonical_id(exercise_id)
    ex_labels = names.labels(ex_id_canon) if ex_id_canon else {
        "exercise": {"he": "", "en": ""},
        "family":   {"he": "", "en": ""},
        "equipment":{"he": "", "en": ""},
    }

    # 2) מפות אליאס למדדים (רק לשם; לא לשינוי ערכים)
    alias_to_canon, spec_by_canon = ({}, {})
    if aliases_yaml:
        alias_to_canon, spec_by_canon = _alias_maps_for_labels(aliases_yaml)

    # 3) מסך המדדים להצגה
    metrics_for_labels: Dict[str, Any] = {}

    if metrics_normalized is not None:
        # כבר קנוני — מעולה. תוויות לפי אותו מפתח.
        metrics_for_labels = dict(metrics_normalized)

    elif raw_metrics is not None:
        # נאתר לכל מפתח raw את שמו הקנוני כדי לתייג; הערך נשאר 1:1.
        for k, v in (raw_metrics or {}).items():
            if not isinstance(k, str):
                continue
            canon = alias_to_canon.get(k, k)  # אם לא מצאנו — נשאיר את המפתח כמו שהוא
            # אם כבר קיים מפתח זהה — לא מאחדים/לא מחשבים ממוצע. לא מתערבים בערכים.
            if canon not in metrics_for_labels:
                metrics_for_labels[canon] = v

    # 4) הפקה ל-UI לפי רמזי פורמט ויחידה
    ml = MetricLabels(_load_yaml(METRICS_YAML), spec_by_canon)
    metrics_ui = ml.pretty_map(metrics_for_labels, lang=lang)

    return {
        "exercise": {
            "id": ex_id_canon or (exercise_id or ""),
            "ui_labels": ex_labels,
        },
        "metrics_ui": metrics_ui,
    }


# ============================== דוגמה להרצה ידנית ============================

if __name__ == "__main__":
    # דוגמה A: יש לי מדדים קנוניים מוכנים מראש (מומלץ בשגרה)
    example_norm = {
        "knee_left_deg": 159.2,
        "rep.timing_s": 1.62,
        "features.stance_width_ratio": 1.07,
        "pose.available": True,
    }
    out_a = build_ui_names(metrics_normalized=example_norm, exercise_id="rdl", lang="he")
    print("[A] normalized → labels")
    print(json.dumps(out_a, ensure_ascii=False, indent=2))

    # דוגמה B: יש raw + aliases רק כדי שנדע איזה תווית לשים (הערכים לא משתנים)
    example_raw = {"knee_angle_left": 159.2, "rep_time_s": 1.62, "pose.ok": True}
    # הערה: כאן לא טוענים aliases.yaml מהדיסק — רק מדגימים מבנה קטן
    demo_aliases = {
        "canonical_keys": {
            "knee_left_deg": {"unit": "deg", "aliases": ["knee_angle_left"]},
            "rep.timing_s":  {"unit": "s",   "aliases": ["rep_time_s"]},
            "pose.available":{"unit": "bool","aliases": ["pose.ok"]},
        }
    }
    out_b = build_ui_names(raw_metrics=example_raw, aliases_yaml=demo_aliases, exercise_id="squat.bw", lang="en")
    print("\n[B] raw+aliases → labels only (values untouched)")
    print(json.dumps(out_b, ensure_ascii=False, indent=2))
