# -*- coding: utf-8 -*-
"""
admin_web/exercise_analyzer.py
==============================
מודול רזה שמרכז את כל הלוגיקה של "ניתוח תרגיל" במקום server.py.

מטרות:
- סימולציה (sets/reps) לצורכי UI ובדיקות ➜ simulate_exercise()
- דו״ח סימולציה מלא (בפורמט analyze_exercise) ➜ build_simulated_report()
- ניקוד דו"ח בודד מתוך metrics (חי/מדומה) ➜ analyze_exercise()
- סניטציה של metrics מהקליינט ➜ sanitize_metrics_payload()

שימוש:
from admin_web.exercise_analyzer import (
    analyze_exercise, simulate_exercise, build_simulated_report, sanitize_metrics_payload
)
"""

from __future__ import annotations
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

# ===== Logging (נופל-בחסד אם core.logs לא קיים) =====
try:
    from core.logs import logger  # type: ignore
except Exception:  # pragma: no cover
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("exercise_analyzer")

__all__ = [
    "sanitize_metrics_payload",
    "simulate_exercise",
    "analyze_exercise",
    "build_simulated_report",
]

# ============ UI constants ============
_UI_COLOR_BAR = [
    {"label": "red",    "from_pct": 0,  "to_pct": 60},
    {"label": "orange", "from_pct": 60, "to_pct": 75},
    {"label": "green",  "from_pct": 75, "to_pct": 100},
]

def _ui_ranges() -> Dict[str, Any]:
    # עטיפה עקבית ל-UI
    return {"color_bar": list(_UI_COLOR_BAR)}

# ============ Utilities ============
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _pct(v: Optional[float]) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(round(float(v) * 100))
    except Exception:
        return None

def _safe_pct(score: Optional[float]) -> Optional[int]:
    if score is None:
        return None
    try:
        return int(round(_clamp01(score) * 100))
    except Exception:
        return None

def _as_float(x) -> Optional[float]:
    try:
        # bool יורש מ-int בפייתון; לא להמיר ל-1.0/0.0
        if isinstance(x, bool):
            return None
        return float(x)
    except Exception:
        return None

def _quality_from_score(score: Optional[float]) -> Optional[str]:
    """
    ממפה ציון כללי לאיכות טכנית – ללא Grade:
      full >= 0.85, partial >= 0.70, אחרת poor.
    """
    if score is None:
        return None
    s = float(score)
    if s >= 0.85:
        return "full"
    if s >= 0.70:
        return "partial"
    return "poor"

# ============ Sanitization ============
def sanitize_metrics_payload(obj: Any) -> Dict[str, Any]:
    """
    מסדר קלט גולמי ל-dict של metrics (מספרים סופיים בלבד + כמה מחרוזות מורשות).
    ✅ שומר בוליאנים כבוליאנים (לא ממיר ל-1.0/0.0).
    """
    out: Dict[str, Any] = {}
    if not isinstance(obj, dict):
        logger.debug("sanitize_metrics_payload: non-dict payload ignored: %r", type(obj))
        return out

    for k, v in obj.items():
        try:
            # ✅ קודם כל בוליאנים – כדי שלא יתפסו כ-int
            if isinstance(v, bool):
                out[k] = v
                continue

            # מספרים סופיים
            if isinstance(v, (int, float)) and math.isfinite(float(v)):
                out[k] = float(v)
                continue

            # מחרוזות: true/false או מספרים כמחרוזת, או מזהים מורשים
            if isinstance(v, str):
                t = v.strip()
                try:
                    tl = t.lower()
                    if tl in ("true", "false"):
                        out[k] = (tl == "true")
                    else:
                        # מנסה להמיר למספר (שלם/צף)
                        fv = float(t) if "." in t else float(int(t))
                        if math.isfinite(fv):
                            out[k] = fv
                except Exception:
                    # מחרוזות מורשות (מזהי תצוגה/מצבים)
                    if k in ("rep.phase", "view.mode", "view.primary", "exercise.id"):
                        out[k] = t
                continue

            # טיפוסים אחרים – מתעלמים בשקט
        except Exception as e:
            logger.warning("sanitize_metrics_payload: skip key=%r err=%s", k, e)

    return out

# ============ Simulation ============
def _mode_to_mean_std(mode: Optional[str], default_mean: float, default_std: float, noise: Optional[float]) -> Tuple[float, float]:
    """
    מפה 'mode' (אם התקבל מהלקוח) לממוצע/סטיית תקן סימולציה.
    """
    m = (mode or "").strip().lower()
    if m == "good":
        base_mean, base_std = 0.85, 0.05
    elif m == "shallow":
        base_mean, base_std = 0.65, 0.10
    elif m == "missing":
        base_mean, base_std = 0.55, 0.15
    elif m == "mixed":
        base_mean, base_std = 0.75, 0.12
    else:
        base_mean, base_std = default_mean, default_std
    if noise is not None:
        try:
            base_std = max(0.0, min(0.5, float(noise)))
        except Exception:
            pass
    return _clamp01(base_mean), base_std

def simulate_exercise(
    sets: int = 1,
    reps: int = 6,
    mean_score: float = 0.75,
    std: float = 0.10,
    # פרמטרים אופציונליים (לא שוברים תאימות): ייתכן ויגיעו מהראוטר
    mode: Optional[str] = None,
    noise: Optional[float] = None,
    seed: Optional[int] = 42,
) -> Dict[str, Any]:
    """
    מייצר דמו (mock) של סט/חזרות — בפורמט שה-UI/בדיקות מצפות.
    מחזיר גם ui_ranges.color_bar. יציב-תוצאות (seed) כדי שבדיקות יהיו עקביות.
    """
    try:
        sets = max(1, min(10, int(sets)))
        reps = max(1, min(30, int(reps)))

        # אם התקבלו mode/noise — נמפה אותם לממוצע/סטיית תקן; אחרת נשארים עם ברירות המחדל
        mean, std = _mode_to_mean_std(mode, _clamp01(mean_score), max(0.0, min(0.5, float(std))), noise)

        rng = random.Random(seed if seed is not None else 42)  # יציב
        sets_out: List[Dict[str, Any]] = []

        for s in range(1, sets + 1):
            reps_list: List[Dict[str, Any]] = []
            for i in range(reps):
                # תנודה קטנה סביב הממוצע (דפוס + רעש רך)
                sign = 1.0 if (i % 2 == 0) else -1.0
                delta = sign * std * (0.9 + 0.2 * rng.random())
                score = _clamp01(round(mean + delta, 3))
                reps_list.append({
                    "rep": i + 1,
                    "score": score,
                    "score_pct": int(round(score * 100)),
                    "notes": [
                        {"crit": "depth", "severity": "med", "text": "עמוק מעט יותר"},
                        {"crit": "knees", "severity": "low", "text": "שמור על ברכיים בקו האצבעות"},
                    ],
                })

            set_score = _clamp01(mean)  # מייצגים את הסט סביב הממוצע
            sets_out.append({
                "set": s,
                "exercise_id": "squat.bodyweight",
                "set_score": round(set_score, 4),
                "set_score_pct": int(round(set_score * 100)),
                "reps": reps_list,
            })

        out = {
            "ok": True,
            "ui_ranges": _ui_ranges(),
            "sets_total": sets,
            "reps_total": reps,
            "sets": sets_out,
        }
        return out
    except Exception as e:
        logger.error("simulate_exercise: unexpected error: %s", e, exc_info=True)
        # נפילה רכה — תחזיר מבנה מינימלי כדי שה-UI לא יקרוס
        return {"ok": False, "error": "simulate_failed", "ui_ranges": _ui_ranges(), "sets": []}

# ============ Analyzer (heuristics) ============
# סט מפתחות עיקרי לציון "סקווט גוף"
_EXPECTED_KEYS = {
    "torso_vs_vertical_deg",  # זווית גב מול אנך
    "knee_angle_left",
    "knee_angle_right",
    "hip_left_deg",
    "hip_right_deg",
    "feet_w_over_shoulders_w",  # יחס רוחב רגליים על רוחב כתפיים
    "rep_time_s",
}

# אליאסים מקובלים (אם יגיעו שמות חלופיים)
_ALIASES = {
    "knee_angle_left":  ("knee_angle_left",  "knee_angle_left_deg"),
    "knee_angle_right": ("knee_angle_right", "knee_angle_right_deg"),
    "torso_vs_vertical_deg": ("torso_vs_vertical_deg",),
    "hip_left_deg": ("hip_left_deg",),
    "hip_right_deg": ("hip_right_deg",),
    "feet_w_over_shoulders_w": ("feet_w_over_shoulders_w",),
    "rep_time_s": ("rep_time_s",),
}

def _first_present(d: Dict[str, Any], names: Tuple[str, ...]):
    for n in names:
        if n in d:
            return d[n]
    return None

def _extract_metrics(payload: Dict[str, Any]) -> Tuple[Dict[str, float], bool]:
    """
    מחלץ metrics מתוך payload (או מתוך obj עם 'metrics'),
    מבצע סניטציה, מחזיר (metrics, has_any).
    """
    m: Dict[str, float] = {}
    has_any = False

    src = None
    if isinstance(payload, dict):
        src = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload

    # סניטציה ראשונית
    clean = sanitize_metrics_payload(src or {})
    if not isinstance(clean, dict):
        return {}, False

    # משיכה לפי אליאסים/מפתחות צפויים
    for key in _EXPECTED_KEYS:
        names = _ALIASES.get(key, (key,))
        v = _first_present(clean, names)
        fv = _as_float(v)
        if fv is not None and math.isfinite(fv):
            m[key] = float(fv)
            has_any = True

    if not has_any:
        logger.debug("extract_metrics: no expected metrics found. keys_in=%s", list((clean or {}).keys()))
    return m, has_any

def _criteria_from_metrics(m: Dict[str, float]) -> List[Dict[str, Any]]:
    """
    מחשב קריטריונים בסיסיים ל"סקווט גוף" בצורה פשטנית אך עקבית.
    """
    crit: List[Dict[str, Any]] = []

    knee_l = m.get("knee_angle_left")
    knee_r = m.get("knee_angle_right")
    hip_l  = m.get("hip_left_deg")
    hip_r  = m.get("hip_right_deg")
    torso  = m.get("torso_vs_vertical_deg")
    stance = m.get("feet_w_over_shoulders_w")
    tempo  = m.get("rep_time_s")

    # depth (מוערך מזוויות ברך/ירך)
    depth_avail = (knee_l is not None and knee_r is not None) or (hip_l is not None and hip_r is not None)
    depth_score = None
    depth_reason = None
    if depth_avail:
        comp = []
        if knee_l is not None and knee_r is not None:
            k_avg = (knee_l + knee_r) / 2.0
            depth_from_knee = _clamp01((170.0 - k_avg) / (170.0 - 110.0))  # 110→1, 170→0
            comp.append(depth_from_knee)
        if hip_l is not None and hip_r is not None:
            h_avg = (hip_l + hip_r) / 2.0
            hip_score = 1.0 - _clamp01(abs(h_avg - 100.0) / 40.0)        # 100±40 טווח
            comp.append(hip_score)
        if comp:
            depth_score = sum(comp) / len(comp)
            if depth_score < 0.5:
                depth_reason = "shallow_depth"
    crit.append({"id": "depth", "available": depth_avail, "score": depth_score, "score_pct": _safe_pct(depth_score), "reason": depth_reason})

    # knees (valgus סימטריה בסיסית)
    knees_avail = (knee_l is not None and knee_r is not None)
    knees_score = None
    knees_reason = None
    if knees_avail:
        delta = abs(knee_l - knee_r)
        knees_score = 1.0 - _clamp01(delta / 20.0)  # 0→1, 20→0
        if knees_score < 0.6:
            knees_reason = "valgus"
    crit.append({"id": "knees", "available": knees_avail, "score": knees_score, "score_pct": _safe_pct(knees_score), "reason": knees_reason})

    # torso angle
    torso_avail = (torso is not None)
    torso_score = None
    if torso_avail:
        torso_score = 1.0 - _clamp01(abs(torso) / 30.0)  # 0–10 טוב; 30→0
    crit.append({"id": "torso_angle", "available": torso_avail, "score": torso_score, "score_pct": _safe_pct(torso_score), "reason": None})

    # stance width
    stance_avail = (stance is not None)
    stance_score = None
    stance_reason = None
    if stance_avail:
        diff = abs((stance or 0.0) - 1.2)           # יעד ~1.2
        stance_score = 1.0 - _clamp01(diff / 0.4)   # 1.1–1.3≈טוב; 0.8/1.6→0
        if stance_score < 0.6:
            stance_reason = "stance_out_of_range"
    crit.append({"id": "stance_width", "available": stance_avail, "score": stance_score, "score_pct": _safe_pct(stance_score), "reason": stance_reason})

    # tempo
    tempo_avail = (tempo is not None)
    tempo_score = None
    if tempo_avail:
        x = float(tempo or 0.0)
        if 1.0 <= x <= 2.0:
            tempo_score = 1.0
        elif x < 1.0:
            tempo_score = 1.0 - _clamp01((1.0 - x) / 0.7)
        else:
            tempo_score = 1.0 - _clamp01((x - 2.0) / 1.0)
    crit.append({"id": "tempo", "available": tempo_avail, "score": tempo_score, "score_pct": _safe_pct(tempo_score), "reason": None})

    return crit

def _criteria_breakdown_pct(criteria: List[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    """
    מחזיר מילון id->score_pct ל-tooltip. אם חסר score_pct אבל יש score, יומר ל-%.
    """
    out: Dict[str, Optional[int]] = {}
    for c in (criteria or []):
        try:
            cid = str(c.get("id") or "")
            if not cid:
                continue
            if c.get("score_pct") is not None:
                out[cid] = int(c["score_pct"])
            elif c.get("score") is not None:
                out[cid] = _safe_pct(float(c["score"]))
            else:
                out[cid] = None
        except Exception:
            # לא מפיל את כל הפונקציה
            pass
    return out

def _overall_from_criteria(criteria: List[Dict[str, Any]]) -> Tuple[Optional[float], Optional[str], List[str], Optional[str]]:
    """
    מחזיר: (overall_score[0..1], quality[str], hints[list], unscored_reason[str|None])
    """
    avail = [c for c in criteria if c.get("available") and (c.get("score") is not None)]
    if not avail:
        logger.warning("overall: no available criteria -> missing_critical")
        return None, None, ["אין מספיק מדדים זמינים כדי לנקד"], "missing_critical"

    avg = sum(float(c["score"]) for c in avail) / max(1, len(avail))
    quality = _quality_from_score(avg)
    hints: List[str] = []

    # קח 2–3 הכי חלשים לרמזים
    weak = sorted(avail, key=lambda c: (c.get("score") or 0.0))[:3]
    for w in weak:
        wid = str(w.get("id") or "criteria")
        sp = _safe_pct(w.get("score"))
        reason = w.get("reason")
        if wid == "depth" and (reason == "shallow_depth" or (sp is not None and sp < 70)):
            hints.append("העמק מעט בתחתית")
        elif wid == "knees" and (reason == "valgus" or (sp is not None and sp < 75)):
            hints.append("שמור על ברכיים בקו האצבעות")
        elif wid == "torso_angle" and (sp is not None and sp < 75):
            hints.append("שמור על גב זקוף יותר")
        elif wid == "stance_width" and (sp is not None and sp < 70):
            hints.append("כוון רוחב עמידה מעט")
        elif wid == "tempo" and (sp is not None and sp < 80):
            hints.append("ווסת את הקצב (1–2 שניות לחזרה)")

    # ייחודיות והגבלה ל-3
    uniq: List[str] = []
    for h in hints:
        if h not in uniq:
            uniq.append(h)
        if len(uniq) >= 3:
            break

    return _clamp01(avg), quality, uniq, None

def analyze_exercise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    ניתוח דו"ח יחיד מתוך metrics. מחזיר מבנה דו"ח בפורמט שה-UI מצפה לו.
    אין Grade במערכת — מחזירים only quality (full/partial/poor).
    """
    try:
        exercise_id = None
        try:
            exercise_id = payload.get("exercise", {}).get("id")
        except Exception:
            pass
        if not isinstance(exercise_id, str) or not exercise_id:
            exercise_id = "squat.bodyweight"

        metrics, has_any = _extract_metrics(payload)
        if not has_any:
            logger.info("analyze_exercise: no metrics -> returning demo unscored")
            # החזרה תואמת UI + כולל ui_ranges ל-Gauges
            return {
                "exercise": {"id": exercise_id},
                "ui_ranges": _ui_ranges(),
                "scoring": {
                    "score": None,
                    "score_pct": None,
                    "quality": None,
                    "unscored_reason": "missing_critical",
                    "criteria": [
                        {"id": "depth", "available": False, "score": None, "score_pct": None, "reason": "missing_critical"},
                        {"id": "knees", "available": False, "score": None, "score_pct": None, "reason": "missing"},
                    ],
                    "criteria_breakdown_pct": {"depth": None, "knees": None},
                },
                "hints": ["אין מספיק מידע לניקוד — ודא שמדדים מוזרמים"],
            }

        criteria = _criteria_from_metrics(metrics)
        overall, quality, hints, unscored_reason = _overall_from_criteria(criteria)

        # breakdown ל-tooltip
        breakdown = _criteria_breakdown_pct(criteria)

        if overall is None:
            logger.warning("analyze_exercise: unscored -> %s", unscored_reason)
            return {
                "exercise": {"id": exercise_id},
                "ui_ranges": _ui_ranges(),
                "scoring": {
                    "score": None,
                    "score_pct": None,
                    "quality": quality,
                    "unscored_reason": unscored_reason or "missing_critical",
                    "criteria": criteria,
                    "criteria_breakdown_pct": breakdown,
                },
                "hints": hints or ["אין מספיק מידע לניקוד — ודא שמדדים מוזרמים"],
            }

        pct = _pct(overall) or 0
        return {
            "exercise": {"id": exercise_id},
            "ui_ranges": _ui_ranges(),
            "scoring": {
                "score": round(float(overall), 4),
                "score_pct": pct,
                "quality": quality,
                "unscored_reason": None,
                "criteria": criteria,
                "criteria_breakdown_pct": breakdown,
            },
            "hints": hints,
        }

    except Exception as e:
        logger.error("analyze_exercise: unexpected error: %s", e, exc_info=True)
        # החזרה רכה כדי שלא יפיל את ה-UI
        return {
            "exercise": {"id": "squat.bodyweight"},
            "ui_ranges": _ui_ranges(),
            "scoring": {
                "score": None, "score_pct": None, "quality": None,
                "unscored_reason": "analyzer_error",
                "criteria": [], "criteria_breakdown_pct": {},
            },
            "hints": ["שגיאת ניתוח – ראה לוגים"],
        }

# ==== דו"ח סימולציה מלא (תואם analyze_exercise, כולל sets/reps) ====
def build_simulated_report(
    mode: str = "mixed",
    sets: int = 1,
    reps: int = 5,
    noise: float = 0.12,
    exercise_id: str = "squat.bodyweight",
    seed: Optional[int] = None,   # אם None -> רנדומלי בכל קליק
) -> Dict[str, Any]:
    """
    מחזיר דו״ח סימולטיבי במבנה זהה ל-analyze_exercise:
    scoring{ score, score_pct, quality, criteria, criteria_breakdown_pct } + ui_ranges + hints.
    בנוסף מצרף תחת המפתח "simulation" את ה-sets/reps הגולמי.
    """
    try:
        if seed is None:
            seed = int(time.time() * 1000) & 0xFFFFFFFF

        sim = simulate_exercise(
            sets=sets, reps=reps, mean_score=0.75, std=0.10,
            mode=mode, noise=noise, seed=seed
        )

        # סיכום ציון כולל מכל החזרות
        all_scores: List[float] = []
        for s in sim.get("sets", []):
            for r in s.get("reps", []):
                sc = r.get("score")
                if isinstance(sc, (int, float)):
                    all_scores.append(float(sc))

        overall = round(float(sum(all_scores) / max(1, len(all_scores))) if all_scores else 0.0, 4)
        pct = int(round(overall * 100))
        quality = _quality_from_score(overall)

        # קריטריונים סימולטיביים עקביים (מעניקים breakdown וטיפים)
        rng = random.Random(seed)
        def _jitter(base: float, amp: float = 0.15) -> float:
            return _clamp01(base + (rng.random() - 0.5) * 2.0 * amp)

        crit_map = [
            ("depth",        _jitter(overall, 0.25)),
            ("knees",        _jitter(overall, 0.20)),
            ("torso_angle",  _jitter(overall, 0.18)),
            ("stance_width", _jitter(overall, 0.20)),
            ("tempo",        _jitter(overall, 0.15)),
        ]
        criteria = [{
            "id": cid, "available": True,
            "score": sc, "score_pct": _safe_pct(sc), "reason": None
        } for cid, sc in crit_map]
        breakdown = {c["id"]: c["score_pct"] for c in criteria}

        # רמזים – 2–3 החלשים
        weak = sorted(criteria, key=lambda c: (c.get("score") or 0.0))[:3]
        hints: List[str] = []
        for w in weak:
            wid = w["id"]
            if wid == "depth":          hints.append("העמק מעט בתחתית")
            elif wid == "knees":        hints.append("שמור על ברכיים בקו האצבעות")
            elif wid == "torso_angle":  hints.append("שמור על גב זקוף יותר")
            elif wid == "stance_width": hints.append("כוון רוחב עמידה מעט")
            elif wid == "tempo":        hints.append("ווסת את הקצב (1–2 שניות לחזרה)")
        hints_uniq: List[str] = []
        for h in hints:
            if h not in hints_uniq:
                hints_uniq.append(h)
            if len(hints_uniq) >= 3:
                break

        return {
            "exercise": {"id": exercise_id},
            "ui_ranges": _ui_ranges(),
            "scoring": {
                "score": overall,
                "score_pct": pct,
                "quality": quality,
                "unscored_reason": None,
                "criteria": criteria,
                "criteria_breakdown_pct": breakdown,
            },
            "hints": hints_uniq or ["המשך ככה!"],
            "simulation": sim,  # ה-sets/reps הגולמי למי שצריך
        }
    except Exception as e:
        logger.error("build_simulated_report failed: %s", e, exc_info=True)
        return {
            "exercise": {"id": exercise_id},
            "ui_ranges": _ui_ranges(),
            "scoring": {
                "score": None, "score_pct": None, "quality": None,
                "unscored_reason": "simulate_failed",
                "criteria": [], "criteria_breakdown_pct": {},
            },
            "hints": ["שגיאת סימולציה – ראה לוגים"],
        }
