# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# db/persist.py
# שכבת אינטגרציה אחידה למסד הנתונים.
# - השרת קורא רק לכאן (persist_report / start_workout / stop_workout / open_set).
# - אם מודולי ה-DB לא קיימים, הכול הופך ל-no-op ולא שובר את השרת.
# שימוש מהשרת:
#   from db.persist import AVAILABLE, init, persist_report, start_workout, stop_workout, open_set
#   init(default_user_name="Amit")
#   ...
#   persist_report(report)  # אחרי שקיבלת דו"ח מ-run_once
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Optional, Dict, Any
import threading
import logging

logger = logging.getLogger("persist")

AVAILABLE = False

try:
    from db.saver import (
        ensure_user, start_workout as _start_workout, close_workout as _close_workout,
        open_set as _open_set, close_set as _close_set, save_reps as _save_reps,
        save_report_snapshot as _save_report_snapshot
    )
    AVAILABLE = True
except Exception as e:
    logger.info(f"[persist] DB modules not available ({e}). Running without persistence.")
    ensure_user = _start_workout = _close_workout = _open_set = _close_set = _save_reps = _save_report_snapshot = None  # type: ignore

_STATE_LOCK = threading.Lock()
_STATE = {
    "user_name": "Amit",
    "user_id": None,       # ימולא ב-init()
    "workout_id": None,
    "set_id": None,
}

def init(default_user_name: str = "Amit") -> None:
    if not AVAILABLE:
        return
    with _STATE_LOCK:
        _STATE["user_name"] = default_user_name or "Amit"
        try:
            _STATE["user_id"] = ensure_user(_STATE["user_name"])  # type: ignore
        except Exception as e:
            logger.warning(f"[persist] ensure_user failed: {e}")

def start_workout() -> Optional[int]:
    if not AVAILABLE:
        return None
    with _STATE_LOCK:
        try:
            if not isinstance(_STATE["user_id"], int):
                _STATE["user_id"] = ensure_user(_STATE["user_name"])  # type: ignore
            wid = _start_workout(_STATE["user_id"])  # type: ignore
            _STATE["workout_id"] = wid
            _STATE["set_id"] = None
            return wid
        except Exception as e:
            logger.warning(f"[persist] start_workout failed: {e}")
            return None

def stop_workout(summary: Dict[str, Any] | None = None) -> bool:
    if not AVAILABLE:
        return False
    with _STATE_LOCK:
        wid = _STATE.get("workout_id")
        _STATE["set_id"] = None
        _STATE["workout_id"] = None
    if not isinstance(wid, int):
        return False
    try:
        _close_workout(wid, summary or {})  # type: ignore
        return True
    except Exception as e:
        logger.warning(f"[persist] close_workout failed: {e}")
        return False

def open_set(exercise_code: str | None) -> Optional[int]:
    if not AVAILABLE:
        return None
    with _STATE_LOCK:
        wid = _STATE.get("workout_id")
        if not isinstance(wid, int):
            wid = start_workout()
        if not isinstance(wid, int):
            return None
        try:
            sid = _open_set(wid, exercise_code)  # type: ignore
            _STATE["set_id"] = sid
            return sid
        except Exception as e:
            logger.warning(f"[persist] open_set failed: {e}")
            return None

def _close_set_from_report(report: Dict[str, Any]) -> None:
    if not AVAILABLE:
        return
    try:
        sc_pct = None
        reps = report.get("reps") if isinstance(report, dict) else None
        try:
            sc_pct = report.get("scoring", {}).get("score_pct")
        except Exception:
            sc_pct = None
        metrics = {}
        try:
            s0 = (report.get("sets") or [None])[0] or {}
            if isinstance(s0, dict):
                for k in ("avg_rom_deg", "avg_tempo_s", "avg_score", "min_score", "max_score", "duration_s"):
                    if k in s0: metrics[k] = s0[k]
        except Exception:
            pass
        with _STATE_LOCK:
            sid = _STATE.get("set_id")
        if isinstance(sid, int):
            _close_set(sid, sc_pct, metrics, len(reps or []))  # type: ignore
    except Exception as e:
        logger.warning(f"[persist] close_set_from_report failed: {e}")

def persist_report(report: Dict[str, Any]) -> Optional[int]:
    """
    נקודה יחידה לשמירה:
      - דואגת שיהיה workout/set פתוח.
      - שומרת report מלא + reps (אם קיימים).
      - סוגרת סט עם נתוני הדו״ח.
    """
    if not AVAILABLE:
        return None
    try:
        with _STATE_LOCK:
            wid = _STATE.get("workout_id")
        if not isinstance(wid, int):
            wid = start_workout()

        ex_code = None
        try:
            ex_code = (report.get("exercise") or {}).get("id")
        except Exception:
            ex_code = None

        with _STATE_LOCK:
            sid = _STATE.get("set_id")
        if not isinstance(sid, int):
            sid = open_set(ex_code if isinstance(ex_code, str) else None)

        with _STATE_LOCK:
            uid = _STATE.get("user_id")
        rep_id = _save_report_snapshot(uid, wid, sid, report)  # type: ignore

        if isinstance(report.get("reps"), list) and report["reps"]:
            _save_reps(sid, report["reps"])  # type: ignore

        _close_set_from_report(report)
        return rep_id
    except Exception as e:
        logger.warning(f"[persist] persist_report failed: {e}")
        return None
