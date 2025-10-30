# -*- coding: utf-8 -*-
"""
admin_web/exercise_analyzer.py
==============================
⚙️ ניתוח תרגיל + סימולציה מלאה + חיבור למנוע Runtime + תוויות UI

מטרות:
- יצירת דו"חות מלאים (score + hints + health + coverage)
- הפקת דו"ח אמיתי ממדידות (detect_once)
- ניקוד בסיסי ללא מנוע (analyze_exercise)
- סימולציה מלאה (simulate_full_reports / simulate_exercise)
- שמירת דו"ח אחרון ל-UI
- טעינת שמות תצוגה (exercises/family/equipment) + תוויות מדדים (metrics)
- הזרקת שמות תצוגה לדו"ח שחוזר מהמנוע
- API פנימי: get_ui_labels()/reload_ui_labels()/settings_dump()
"""

from __future__ import annotations
import os, math, random, time, json, threading
from typing import Any, Dict, List, Optional, Tuple, Callable
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# לוגינג
# ─────────────────────────────────────────────────────────────
try:
    from core.logs import logger  # type: ignore
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("exercise_analyzer")

# ─────────────────────────────────────────────────────────────
# ייבוא מנוע runtime (לא מוחקים!)
# ─────────────────────────────────────────────────────────────
try:
    from exercise_engine.runtime.runtime import run_once as exr_run_once
    from exercise_engine.runtime.engine_settings import SETTINGS as EXR_SETTINGS
    from exercise_engine.registry.loader import load_library as exr_load_library
    _EXR_OK = True
except Exception as _e:
    logger.warning(f"[EXR] engine imports failed: {_e}")
    _EXR_OK = False
    exr_run_once = None
    EXR_SETTINGS = None
    exr_load_library = None

_ENGINE = {"lib": None, "root": None}
_ENGINE_LOCK = threading.Lock()

def configure_engine_root(root_dir: Optional[str]) -> None:
    """מאפשר לקבוע ספריית תרגילים חיצונית."""
    _ENGINE["root"] = root_dir

def get_engine_library():
    """טוען את ספריית התרגילים (exercise_library)."""
    if not _EXR_OK:
        raise RuntimeError("exercise engine not available")
    if _ENGINE["lib"] is not None:
        return _ENGINE["lib"]
    with _ENGINE_LOCK:
        if _ENGINE["lib"] is not None:
            return _ENGINE["lib"]
        default_root = Path(__file__).resolve().parent.parent / "exercise_library"
        lib_dir = Path(_ENGINE["root"] or default_root)
        lib = exr_load_library(lib_dir)
        logger.info(f"[EXR] library loaded @ {lib_dir}")
        _ENGINE["lib"] = lib
        return lib

# ─────────────────────────────────────────────────────────────
# UI Labels (exercise_names.yaml + metrics_labels.yaml)
# ─────────────────────────────────────────────────────────────
import yaml

_UI_LABELS: Dict[str, Any] = {"names": {}, "labels": {}}
_UI_LABELS_LOCK = threading.Lock()

def _ui_files_base() -> Path:
    """
    מיקום ברירת מחדל של קבצי התוויות:
    exercise_engine/report/exercise_names.yaml
    exercise_engine/report/metrics_labels.yaml
    """
    return (Path(__file__).resolve().parent.parent / "exercise_engine" / "report")

def _load_ui_labels(root: Optional[Path] = None) -> Dict[str, Any]:
    """טוען YAML של שמות תצוגה ותוויות מדדים."""
    base = (root or _ui_files_base())
    out = {"names": {}, "labels": {}}
    try:
        with open(base / "exercise_names.yaml", "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
            out["names"] = d.get("names", {})
    except Exception as e:
        logger.warning(f"[UI] failed to load exercise_names.yaml: {e}")

    try:
        with open(base / "metrics_labels.yaml", "r", encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
            out["labels"] = d.get("labels", {})
    except Exception as e:
        logger.warning(f"[UI] failed to load metrics_labels.yaml: {e}")
    return out

def get_ui_labels() -> Dict[str, Any]:
    """החזרת המפות הטעונות (ל־API/UI)."""
    with _UI_LABELS_LOCK:
        return {"names": dict(_UI_LABELS.get("names", {})),
                "labels": dict(_UI_LABELS.get("labels", {}))}

def reload_ui_labels() -> Dict[str, Any]:
    """טעינה מחדש של קבצי התוויות (ללא אתחול שרת)."""
    global _UI_LABELS
    new_maps = _load_ui_labels()
    with _UI_LABELS_LOCK:
        _UI_LABELS = new_maps
        counts = {
            "exercises": len((_UI_LABELS.get("names") or {}).get("exercises", {})),
            "families":  len((_UI_LABELS.get("names") or {}).get("families", {})),
            "equipment": len((_UI_LABELS.get("names") or {}).get("equipment", {})),
            "metrics":   len(_UI_LABELS.get("labels", {})),
        }
    logger.info(f"[UI] labels reloaded: {counts}")
    return {"ok": True, "counts": counts}

def _apply_ui_names(report: Dict[str, Any], *, display_lang: str = "he") -> Dict[str, Any]:
    """מוסיף/מעדכן ui.lang_labels לדו״ח לפי exercise_names.yaml (ללא שינוי ציונים/מדידות)."""
    if not isinstance(report, dict):
        return report

    ui = report.setdefault("ui", {})
    names = get_ui_labels().get("names", {}) or {}

    ex = (report.get("exercise") or {})
    ex_id = ex.get("id")
    family = ex.get("family")
    equipment = ex.get("equipment")

    def _lbl(map_name: str, key: Optional[str]) -> Dict[str, str]:
        if not key:
            return {"he": "-", "en": "-"}
        m = (names.get(map_name) or {})
        d = (m.get(key) or {})
        return {"he": d.get("he", key), "en": d.get("en", key)}

    ui["lang_labels"] = {
        "exercise": _lbl("exercises", ex_id),
        "family":   _lbl("families",  family),
        "equipment":_lbl("equipment", equipment),
    }
    report["display_lang"] = display_lang
    return report

# ─────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _pct(v: Optional[float]) -> Optional[int]:
    if v is None: return None
    try: return int(round(float(v) * 100))
    except Exception: return None

def _quality_from_score(score: Optional[float]) -> Optional[str]:
    if score is None: return None
    s = float(score)
    if s >= 0.85: return "full"
    if s >= 0.70: return "partial"
    return "poor"

def _ui_ranges() -> Dict[str, Any]:
    return {"color_bar": [
        {"label": "red", "from_pct": 0, "to_pct": 60},
        {"label": "orange", "from_pct": 60, "to_pct": 75},
        {"label": "green", "from_pct": 75, "to_pct": 100},
    ]}

# ─────────────────────────────────────────────────────────────
# Sanitization (ניקוי מדדים גולמיים)
# ─────────────────────────────────────────────────────────────
def sanitize_metrics_payload(obj: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not isinstance(obj, dict):
        return out
    for k, v in obj.items():
        try:
            if isinstance(v, bool):
                out[k] = v
            elif isinstance(v, (int, float)) and math.isfinite(float(v)):
                out[k] = float(v)
            elif isinstance(v, str):
                t = v.strip().lower()
                if t in ("true", "false"):
                    out[k] = (t == "true")
                else:
                    try:
                        out[k] = float(v)
                    except Exception:
                        out[k] = v
        except Exception:
            continue
    return out

# ─────────────────────────────────────────────────────────────
# Settings dump (למסך הגדרות)
# ─────────────────────────────────────────────────────────────
def settings_dump() -> Dict[str, Any]:
    """מצב מנוע/ספרייה להצגה ב־/api/exercise/settings."""
    try:
        engine_ok = EXR_SETTINGS is not None
        lib_root = None
        families_count = exercises_count = 0
        if engine_ok:
            try:
                lib = get_engine_library()
                lib_root = getattr(lib, "root_dir", None) or getattr(lib, "root", None)
                families_count = len(getattr(lib, "families", {}) or {})
                exercises_count = len(getattr(lib, "exercises", {}) or {})
            except Exception as e:
                return {"ok": False, "error": f"library_load_failed: {e}", "engine": {"available": False}}

        return {
            "ok": True,
            "engine": {"available": engine_ok, "settings_present": bool(EXR_SETTINGS is not None)},
            "library": {
                "loaded": bool(engine_ok),
                "root": str(lib_root) if lib_root else None,
                "families_count": families_count,
                "exercises_count": exercises_count,
            },
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─────────────────────────────────────────────────────────────
# Detect once (הרצה אמיתית של מנוע)
# ─────────────────────────────────────────────────────────────
def detect_once(raw_metrics: Dict[str, Any],
                exercise_id: Optional[str] = None,
                payload_version: str = "1.0",
                persist_cb: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """הרצה אחת אמיתית של מנוע הזיהוי."""
    if not _EXR_OK or exr_run_once is None:
        return {"ok": False, "error": "engine_unavailable"}

    metrics = sanitize_metrics_payload(raw_metrics)
    ex_id = exercise_id if isinstance(exercise_id, str) else None

    try:
        lib = get_engine_library()
    except Exception as e:
        return {"ok": False, "error": f"library_load_failed: {e}"}

    t0 = time.time()
    try:
        report = exr_run_once(raw_metrics=metrics, library=lib, exercise_id=ex_id, payload_version=payload_version)
    except Exception as e:
        logger.error(f"detect_once runtime failed: {e}")
        return {"ok": False, "error": f"runtime_failed: {e}"}

    # עיטור תצוגה
    try:
        report = _apply_ui_names(report, display_lang="he")
    except Exception as e:
        logger.warning(f"[UI] failed to apply ui names: {e}")

    # שמירה + התמדה (אופציונלי)
    try:
        set_last_report(report)
    except Exception:
        pass
    try:
        if callable(persist_cb):
            persist_cb(report)
    except Exception as e:
        logger.warning(f"[DB] persist callback failed: {e}")

    took_ms = int((time.time() - t0) * 1000)
    return {"ok": True, "took_ms": took_ms, "report": report}

# ─────────────────────────────────────────────────────────────
# ניקוד בסיסי ללא מנוע (לראוט /score)
# ─────────────────────────────────────────────────────────────
def analyze_exercise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    קולט: { metrics: {...}, exercise?: {id/family/equipment} }
    מחזיר דו"ח בדומה ל-runtime אך על בסיס היוריסטיקות פשוטות.
    """
    metrics = sanitize_metrics_payload(payload.get("metrics") or {})
    ex = payload.get("exercise") or {}
    ex_id = (ex.get("id") or "squat.bodyweight")
    family = ex.get("family") or ("squat" if ex_id.startswith("squat") else None)
    equipment = ex.get("equipment") or ("none" if ".bodyweight" in ex_id else None)

    # היוריסטיקה מאוד עדינה: ממוצע של כמה אינדיקטורים אם קיימים
    parts: List[float] = []
    def add(key: str, transform: Callable[[float], float]) -> None:
        v = metrics.get(key)
        if isinstance(v, (int, float)):
            try:
                parts.append(_clamp01(transform(float(v))))
            except Exception:
                pass

    # עומק סקוואט (ברך נמוכה=טוב) 90° יעד
    add("knee_left_deg",  lambda x: (150 - min(150, x)) / 150.0)
    add("knee_right_deg", lambda x: (150 - min(150, x)) / 150.0)

    # זווית גו (הימנעות מקיצוניות)
    add("torso_forward_deg", lambda x: 1.0 - min(abs(x - 35.0), 60.0) / 60.0)

    # טמפו
    add("rep.timing_s", lambda s: 1.0 - min(abs(s - 1.5), 2.0) / 2.0)

    if not parts:
        parts = [0.72]  # ברירת מחדל נעימה לעין אם אין מדדים

    base = sum(parts) / len(parts)
    base = _clamp01(base)

    crit = [
        {"id": "depth",        "available": True, "score": _clamp01(base - 0.05)},
        {"id": "knees",        "available": True, "score": _clamp01(base - 0.03)},
        {"id": "torso_angle",  "available": True, "score": _clamp01(base - 0.02)},
        {"id": "stance_width", "available": True, "score": _clamp01(base - 0.02)},
        {"id": "tempo",        "available": True, "score": _clamp01(base - 0.02)},
    ]
    for c in crit:
        c["score_pct"] = _pct(c["score"])

    overall = sum(c["score"] for c in crit) / len(crit)
    quality = _quality_from_score(overall)
    hints: List[str] = []
    if overall < 0.7: hints.append("העמק מעט יותר ותשמור על קצב קבוע")
    elif overall < 0.8: hints.append("שפר קלות את היציבות והעומק")

    report = {
        "exercise": {"id": ex_id, "family": family, "equipment": equipment},
        "ui_ranges": _ui_ranges(),
        "scoring": {
            "score": round(overall, 3),
            "score_pct": _pct(overall),
            "quality": quality,
            "criteria": crit,
        },
        "hints": hints,
        "report_health": {
            "status": ("FAIL" if overall < 0.6 else "WARN" if overall < 0.7 else "OK"),
            "issues": [] if overall >= 0.7 else [{"code": "LOW_SCORE", "message": "ציון נמוך"}]
        },
        "metrics": metrics,  # נחמד לדיבוג
    }

    # עיטור תצוגה ושמירה אחרונה
    report = _apply_ui_names(report, display_lang="he")
    try: set_last_report(report)
    except Exception: pass
    return {"ok": True, "report": report}

# ─────────────────────────────────────────────────────────────
# סימולציה מלאה (כולל דו"חות)
# ─────────────────────────────────────────────────────────────
def simulate_full_reports(sets: int = 2,
                          reps: int = 5,
                          mode: str = "mixed",
                          noise: float = 0.2,
                          mean_score: float = 0.75,
                          std: float = 0.10,
                          seed: Optional[int] = None) -> Dict[str, Any]:
    """
    יוצר דו"חות מלאים (כמו analyze_exercise) לכל חזרה.
    כולל אינדיקציות, סטטוס, ציונים וטיפים.
    """
    stats = {"reports": 0, "ok": 0, "warn": 0, "fail": 0, "avg_score_pct": 0}
    sets_out = []
    rng = random.Random(seed if seed is not None else time.time())

    def clamp(x): return max(0.0, min(1.0, x))

    for s in range(1, sets + 1):
        reps_out = []
        for r in range(1, reps + 1):
            base = clamp(rng.gauss(mean_score, std))
            crit = [
                {"id": "depth",        "available": True, "score": clamp(base - rng.uniform(0, noise))},
                {"id": "knees",        "available": True, "score": clamp(base - rng.uniform(0, noise * 0.8))},
                {"id": "torso_angle",  "available": True, "score": clamp(base - rng.uniform(0, noise * 0.6))},
                {"id": "stance_width", "available": True, "score": clamp(base - rng.uniform(0, noise * 0.6))},
                {"id": "tempo",        "available": True, "score": clamp(base - rng.uniform(0, noise * 0.6))},
            ]
            for c in crit:
                c["score_pct"] = _pct(c["score"])

            overall = sum(c["score"] for c in crit) / len(crit)
            quality = _quality_from_score(overall)
            hints: List[str] = []
            if overall < 0.7: hints.append("העמק מעט יותר ותשמור על קצב קבוע")
            elif overall < 0.8: hints.append("שפר קלות את היציבות והעומק")

            report = {
                "exercise": {"id": "squat.bodyweight", "family": "squat", "equipment": "none"},
                "ui_ranges": _ui_ranges(),
                "scoring": {
                    "score": round(overall, 3),
                    "score_pct": _pct(overall),
                    "quality": quality,
                    "criteria": crit,
                },
                "hints": hints,
                "report_health": {
                    "status": ("FAIL" if overall < 0.6 else "WARN" if overall < 0.7 else "OK"),
                    "issues": [] if overall >= 0.7 else [{"code": "LOW_SCORE", "message": "ציון נמוך"}]
                },
            }

            report = _apply_ui_names(report, display_lang="he")
            reps_out.append({"rep": r, "report": report})
            stats["reports"] += 1
            stats["avg_score_pct"] += _pct(overall) or 0
            if report["report_health"]["status"] == "OK": stats["ok"] += 1
            elif report["report_health"]["status"] == "WARN": stats["warn"] += 1
            else: stats["fail"] += 1

        sets_out.append({"set": s, "reps": reps_out})

    stats["avg_score_pct"] = int(stats["avg_score_pct"] / max(1, stats["reports"]))
    return {"ok": True, "ui_ranges": _ui_ranges(), "sets": sets_out, "stats": stats}

# תאימות: ה-UI קורא ל-simulate_exercise עם mean_score/std
def simulate_exercise(sets: int = 1,
                      reps: int = 6,
                      mean_score: float = 0.75,
                      std: float = 0.10,
                      mode: str | None = None,
                      noise: float | None = None,
                      seed: int | None = 42) -> Dict[str, Any]:
    return simulate_full_reports(
        sets=sets,
        reps=reps,
        mode=mode or "mixed",
        noise=noise if noise is not None else 0.2,
        mean_score=mean_score,
        std=std,
        seed=seed,
    )

# ─────────────────────────────────────────────────────────────
# דו"ח אחרון (לכפתור פירוט)
# ─────────────────────────────────────────────────────────────
_LAST_REPORT: Optional[Dict[str, Any]] = None
_LAST_REPORT_LOCK = threading.Lock()

def set_last_report(report: Dict[str, Any]) -> None:
    with _LAST_REPORT_LOCK:
        global _LAST_REPORT
        _LAST_REPORT = dict(report)

def get_last_report() -> Optional[Dict[str, Any]]:
    with _LAST_REPORT_LOCK:
        return _LAST_REPORT.copy() if isinstance(_LAST_REPORT, dict) else None

# ─────────────────────────────────────────────────────────────
# טעינה ראשונית של תוויות UI בעליית המודול
# ─────────────────────────────────────────────────────────────
try:
    reload_ui_labels()
except Exception as _e:
    logger.warning(f"[UI] initial labels load failed: {_e}")
