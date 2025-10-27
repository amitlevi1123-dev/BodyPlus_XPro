# -*- coding: utf-8 -*-
"""
admin_web/exercise_analyzer.py
==============================
⚙️ ניתוח תרגיל + סימולציה מלאה + חיבור למנוע Runtime

מטרות:
- יצירת דו"חות מלאים (score + hints + health + coverage)
- הפקת דו"ח אמיתי ממדידות (detect_once)
- סימולציה מלאה (simulate_full_reports)
- שמירת דו"ח אחרון ל-UI
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

def _ui_ranges():
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
# Detect once (הרצה אמיתית של מנוע)
# ─────────────────────────────────────────────────────────────
def detect_once(raw_metrics: Dict[str, Any],
                exercise_id: Optional[str] = None,
                payload_version: str = "1.0") -> Dict[str, Any]:
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

    took_ms = int((time.time() - t0) * 1000)
    return {"ok": True, "took_ms": took_ms, "report": report}

# ─────────────────────────────────────────────────────────────
# סימולציה מלאה (כולל דו"חות)
# ─────────────────────────────────────────────────────────────
def simulate_full_reports(sets: int = 2,
                          reps: int = 5,
                          mode: str = "mixed",
                          noise: float = 0.2) -> Dict[str, Any]:
    """
    יוצר דו"חות מלאים (כמו analyze_exercise) לכל חזרה.
    כולל אינדיקציות, סטטוס, ציונים וטיפים.
    """
    stats = {"reports": 0, "ok": 0, "warn": 0, "fail": 0, "avg_score_pct": 0}
    sets_out = []
    rng = random.Random(time.time())

    for s in range(1, sets + 1):
        reps_out = []
        for r in range(1, reps + 1):
            # ציוני קריטריונים
            base = rng.uniform(0.6, 0.95)
            crit = [
                {"id": "depth", "available": True, "score": base - rng.uniform(0, 0.2)},
                {"id": "knees", "available": True, "score": base - rng.uniform(0, 0.15)},
                {"id": "torso_angle", "available": True, "score": base - rng.uniform(0, 0.1)},
                {"id": "stance_width", "available": True, "score": base - rng.uniform(0, 0.1)},
                {"id": "tempo", "available": True, "score": base - rng.uniform(0, 0.1)},
            ]
            for c in crit:
                c["score"] = max(0.0, min(1.0, c["score"]))
                c["score_pct"] = _pct(c["score"])

            overall = sum(c["score"] for c in crit) / len(crit)
            quality = _quality_from_score(overall)
            hints = []
            if overall < 0.7: hints.append("העמק מעט יותר ותשמור על קצב קבוע")
            elif overall < 0.8: hints.append("שפר קלות את היציבות והעומק")

            report = {
                "exercise": {"id": "squat.bodyweight"},
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

            reps_out.append({"rep": r, "report": report})
            stats["reports"] += 1
            stats["avg_score_pct"] += _pct(overall) or 0
            if report["report_health"]["status"] == "OK": stats["ok"] += 1
            elif report["report_health"]["status"] == "WARN": stats["warn"] += 1
            else: stats["fail"] += 1

        sets_out.append({"set": s, "reps": reps_out})

    stats["avg_score_pct"] = int(stats["avg_score_pct"] / max(1, stats["reports"]))
    return {"ok": True, "ui_ranges": _ui_ranges(), "sets": sets_out, "stats": stats}

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
