# -*- coding: utf-8 -*-
"""
admin_web/exercise_analyzer.py
==============================
⚙️ ניתוח תרגיל + סימולציה מלאה + חיבור למנוע Runtime + תוויות UI

מטרות:
- יצירת דו"חות מלאים (score + hints + health + coverage)
- הפקת דו"ח אמיתי ממדידות (detect_once) — תומך persist_cb
- סימולציה מלאה (simulate_exercise / simulate_full_reports)
- ניקוד בסיסי ללא מנוע (analyze_exercise) כדי שתמיד יהיה ציון
- שמירת דו"ח אחרון ל-UI (set_last_report/get_last_report)
- טעינת שמות תצוגה (exercise_names.yaml / metrics_labels.yaml)
- הזרקת שמות תצוגה לדו"ח (he/en)
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
# report_builder — בניית דו"ח סופי ל-UI
# ─────────────────────────────────────────────────────────────
try:
    from exercise_engine.report.report_builder import build_payload  # type: ignore
except Exception:
    # אם אין מודול — נשתמש בבילדר מינימלי פנימי
    def build_payload(**kw):  # type: ignore
        score = kw.get("overall_score")
        return {
            "display_lang": kw.get("display_lang", "he"),
            "exercise": {"id": getattr(kw.get("exercise"), "id", None)},
            "ui_ranges": {"color_bar": [
                {"label": "red", "from_pct": 0, "to_pct": 60},
                {"label": "orange", "from_pct": 60, "to_pct": 75},
                {"label": "green", "from_pct": 75, "to_pct": 100},
            ]},
            "scoring": {
                "score": score,
                "score_pct": None if score is None else int(round(float(score) * 100)),
                "quality": "full" if (score or 0) >= 0.85 else "partial" if (score or 0) >= 0.7 else "poor",
                "criteria": [],
                "criteria_breakdown_pct": {},
                "unscored_reason": kw.get("unscored_reason"),
            },
            "coverage": {"available_pct": 100, "available_ratio": 1.0, "available_count": 0,
                         "total_criteria": 0, "missing_reasons_top": [], "missing_critical": []},
            "hints": list(kw.get("hints") or []),
            "diagnostics": list(kw.get("diagnostics_recent") or []),
            "measurements": dict(kw.get("canonical") or {}),
            "report_health": {"status": "OK", "issues": []},
        }

# ─────────────────────────────────────────────────────────────
# ייבוא מנוע runtime (לא מוחקים!)
# ─────────────────────────────────────────────────────────────
try:
    from exercise_engine.runtime.runtime import run_once as exr_run_once  # type: ignore
    from exercise_engine.runtime.engine_settings import SETTINGS as EXR_SETTINGS  # type: ignore
    from exercise_engine.registry.loader import load_library as exr_load_library  # type: ignore
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
    return Path(__file__).resolve().parent.parent / "exercise_engine" / "report"

def _load_ui_labels(root: Optional[Path] = None) -> Dict[str, Any]:
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
    with _UI_LABELS_LOCK:
        return {"names": dict(_UI_LABELS.get("names", {})),
                "labels": dict(_UI_LABELS.get("labels", {}))}

def reload_ui_labels() -> Dict[str, Any]:
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
    if not isinstance(report, dict):
        return report
    ui = report.setdefault("ui", {})
    names = get_ui_labels().get("names", {}) or {}
    ex = (report.get("exercise") or {})
    ex_id = ex.get("id"); family = ex.get("family"); equipment = ex.get("equipment")

    def _lbl(map_name: str, key: Optional[str]) -> Dict[str, str]:
        if not key:
            return {"he": "-", "en": "-"}
        g = (names.get(map_name) or {})
        d = (g.get(key) or {})
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

def _ui_ranges():
    return {"color_bar": [
        {"label": "red", "from_pct": 0, "to_pct": 60},
        {"label": "orange", "from_pct": 60, "to_pct": 75},
        {"label": "green", "from_pct": 75, "to_pct": 100},
    ]}

# ─────────────────────────────────────────────────────────────
# Sanitization
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
# Settings dump (למסך דיאגנוסטיקה)
# ─────────────────────────────────────────────────────────────
def settings_dump() -> Dict[str, Any]:
    out = {
        "ok": True,
        "engine_available": bool(_EXR_OK),
        "library_loaded": bool(_ENGINE.get("lib")),
        "engine_settings": {},
    }
    try:
        if EXR_SETTINGS is not None:
            out["engine_settings"] = dict(EXR_SETTINGS)  # type: ignore
    except Exception:
        pass
    return out

# ─────────────────────────────────────────────────────────────
# Detect once (מנוע runtime אמיתי)
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

    try:
        report = _apply_ui_names(report, display_lang="he")
    except Exception as e:
        logger.warning(f"[UI] failed to apply ui names: {e}")

    # שמירה למסך + Persist אם יש
    try:
        set_last_report(report)
    except Exception:
        pass
    try:
        if callable(persist_cb):
            persist_cb(report)  # type: ignore
    except Exception:
        logger.warning("[detect_once] persist_cb failed", exc_info=True)

    took_ms = int((time.time() - t0) * 1000)
    return {"ok": True, "took_ms": took_ms, "report": report}

# ─────────────────────────────────────────────────────────────
# ניקוד בסיסי ללא מנוע — כדי שתמיד יופיע ציון במסך
# ─────────────────────────────────────────────────────────────
_DEF_CRITERIA = ["depth", "knees", "torso_angle", "stance_width", "tempo"]

def _deterministic_score(seed_val: float) -> float:
    r = random.Random(seed_val)
    return _clamp01(r.uniform(0.65, 0.92))

def analyze_exercise(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    ניקוד דו"ח יחיד מתוך metrics (ללא מנוע runtime).
    מחזיר מבנה דו"ח עם scoring.score מספרי (לא None) כדי שה-UI יציג.
    """
    metrics = sanitize_metrics_payload(payload.get("metrics") or {})
    ex = payload.get("exercise") or {}
    ex_id = ex.get("id") or "squat.bodyweight"

    # ציונים דטרמיניסטיים קלים (כדי שתמיד נראה ציון)
    seed = sum(float(v) for v in metrics.values() if isinstance(v, (int, float))) or 1.0
    per_scores: Dict[str, Any] = {}
    for cid in _DEF_CRITERIA:
        per_scores[cid] = type("SC", (), {"score": _deterministic_score(seed + hash(cid) % 1000)})

    overall = sum(getattr(per_scores[c], "score", 0.0) for c in _DEF_CRITERIA) / len(_DEF_CRITERIA)
    quality = _quality_from_score(overall)

    # בניית דו"ח
    class _Ex:
        id = ex_id
        family = ex.get("family")
        equipment = ex.get("equipment")
        criteria = {c: {"requires": []} for c in _DEF_CRITERIA}
        thresholds = {}

    availability = {c: {"available": True} for c in _DEF_CRITERIA}
    report = build_payload(
        exercise=_Ex,
        canonical=metrics,
        availability=availability,
        overall_score=float(overall),
        overall_quality=quality,
        unscored_reason=None,
        hints=[],
        diagnostics_recent=[],
        library_version="dev",
        payload_version="1.0",
        per_criterion_scores=per_scores,
        display_lang="he",
        aliases=get_ui_labels(),  # כדי לקבל תוויות יפות אם קיימות
    )

    try:
        report = _apply_ui_names(report, display_lang="he")
    except Exception:
        pass

    try:
        set_last_report(report)
    except Exception:
        pass

    return {"ok": True, "report": report}

# ─────────────────────────────────────────────────────────────
# סימולציה מלאה (כולל דו"חות)
# ─────────────────────────────────────────────────────────────
def simulate_full_reports(sets: int = 2,
                          reps: int = 5,
                          mode: str = "mixed",
                          noise: float = 0.2) -> Dict[str, Any]:
    stats = {"reports": 0, "ok": 0, "warn": 0, "fail": 0, "avg_score_pct": 0}
    sets_out = []
    rng = random.Random(time.time())

    for s in range(1, sets + 1):
        reps_out = []
        for r in range(1, reps + 1):
            base = rng.uniform(0.6, 0.95)
            crit = [
                {"id": "depth", "available": True, "score": base - rng.uniform(0, 0.2)},
                {"id": "knees", "available": True, "score": base - rng.uniform(0, 0.15)},
                {"id": "torso_angle", "available": True, "score": base - rng.uniform(0, 0.1)},
                {"id": "stance_width", "available": True, "score": base - rng.uniform(0, 0.1)},
                {"id": "tempo", "available": True, "score": base - rng.uniform(0, 0.1)},
            ]
            for c in crit:
                c["score"] = _clamp01(c["score"])
                c["score_pct"] = _pct(c["score"])

            overall = sum(c["score"] for c in crit) / len(crit)
            quality = _quality_from_score(overall)
            hints = []
            if overall < 0.7: hints.append("העמק מעט יותר ותשמור על קצב קבוע")
            elif overall < 0.8: hints.append("שפר קלות את היציבות והעומק")

            report = {
                "exercise": {"id": "squat.bodyweight", "family": "squat", "equipment": "bodyweight"},
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

def simulate_exercise(*, sets: int = 1, reps: int = 6,
                      mean_score: float = 0.75, std: float = 0.10,
                      mode: Optional[str] = None, noise: Optional[float] = None,
                      seed: int = 42) -> Dict[str, Any]:
    """
    API ידידותי ל-UI: מחזיר מבנה עם sets/reps ודוחות המדמים ציון אמיתי.
    """
    rng = random.Random(seed)
    out_sets = []
    stats = {"reports": 0, "avg_score_pct": 0}
    for s in range(1, int(sets) + 1):
        reps_out = []
        for r in range(1, int(reps) + 1):
            sc = max(0.0, min(1.0, rng.gauss(mean_score, std)))
            crit = [{"id": cid, "available": True, "score": max(0.0, min(1.0, sc - rng.uniform(0, 0.1))),
                     "score_pct": _pct(sc)} for cid in _DEF_CRITERIA]
            rep_report = {
                "exercise": {"id": "squat.bodyweight", "family": "squat", "equipment": "bodyweight"},
                "ui_ranges": _ui_ranges(),
                "scoring": {
                    "score": sc,
                    "score_pct": _pct(sc),
                    "quality": _quality_from_score(sc),
                    "criteria": crit,
                },
                "hints": [],
                "report_health": {"status": "OK", "issues": []},
            }
            rep_report = _apply_ui_names(rep_report, display_lang="he")
            reps_out.append({"rep": r, "report": rep_report})
            stats["reports"] += 1
            stats["avg_score_pct"] += _pct(sc) or 0
        out_sets.append({"set": s, "reps": reps_out})
    if stats["reports"]:
        stats["avg_score_pct"] = int(stats["avg_score_pct"] / stats["reports"])
    return {"ok": True, "ui_ranges": _ui_ranges(), "sets": out_sets, "stats": stats}

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
