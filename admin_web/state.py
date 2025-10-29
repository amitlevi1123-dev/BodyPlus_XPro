# -*- coding: utf-8 -*-
# =============================================================================
# admin_web/state.py — מצב ותווך זיכרון לשרת הניהול (Thread-Safe, בלי I/O)
# -----------------------------------------------------------------------------
# מה הקובץ עושה?
# 1) set_payload / get_payload  — צילום מצב חי (payload) שמגיע מהמנוע.
# 2) add_log / get_logs...      — מאגר טבעתי של לוגים אחרונים ל-/api/logs.
# 3) set_od_engine / ...        — גשר קל למנוע זיהוי אובייקטים (OD) אם חי.
# 4) update_od_status / ...     — סטטוס מהיר ל-UI (FPS/latency/ספירה/ספק).
# 5) push_frame_np / get_frame  — Buffer גנרי לפריימים RGB מכל מקור (דפדפן/קובץ/RTSP).
#
# עקרונות:
# • הכל בזיכרון (in-memory), thread-safe, ללא תלות ב-Flask/OpenCV.
# • החתימות פשוטות וחסינות — השכבות העליונות לא צריכות לדעת מקור צילום.
# • אם רכיב לא מחובר — הפונקציות מחזירות מצב “בריא” כברירת מחדל.
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List, Optional
from collections import deque
from threading import Lock
from time import time
from copy import deepcopy
import os
import math

__all__ = [
    # Payload
    "set_payload", "get_payload",
    # Logs
    "add_log", "get_logs", "clear_logs", "get_logs_since",
    # Object Detection Engine bridge
    "set_od_engine", "get_od_engine", "get_od_snapshot",
    # Lightweight OD status (for UI cards/diag)
    "update_od_status", "get_od_status",
    # Generic Frame Buffer (RGB)
    "push_frame_np", "get_frame", "is_frame_ready",
    "set_frame_provider_name", "get_frame_provider_name",
]

# -----------------------------------------------------------------------------
# Logger (אופציונלי; אם core.logs לא קיים, נחליק בשקט)
# -----------------------------------------------------------------------------
try:
    from core.logs import logger  # type: ignore
    _HAS_LOGGER = True
except Exception:
    _HAS_LOGGER = False

    class _NoLog:
        def debug(self, *a, **k): pass
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    logger = _NoLog()  # type: ignore


# =============================================================================
# 1) PAYLOAD — צילום מצב חי מהמנוע (לשימוש /payload, UI, דוחות)
# =============================================================================

_last_payload: Dict[str, Any] = {"ts": 0, "pixels": {}, "metrics": {}}
_payload_lock = Lock()

# תקרות הגנה לגודל אובייקטים שמוחזרים ל-Frontend
_MAX_LANDMARKS = 99
_MAX_OBJECTS   = 256
_MAX_TRACKS    = 256


def _sanitize_payload(p: Dict[str, Any]) -> Dict[str, Any]:
    """
    מנקה/משלים שדות כדי לשמור על יציבות השרת וה-Frontend.
    לא זורק חריגות — תמיד יחזיר אובייקט “בריא”.
    """
    out = dict(p)

    # זמן מערכת
    if "ts_ms" not in out:
        out["ts_ms"] = int(time() * 1000)
    out.setdefault("ts", out["ts_ms"] / 1000.0)

    # mp.landmarks — ודא רשימה וקיצוץ
    mp = out.get("mp")
    if isinstance(mp, dict):
        lms = mp.get("landmarks")
        if isinstance(lms, list) and len(lms) > _MAX_LANDMARKS:
            mp["landmarks"] = lms[:_MAX_LANDMARKS]
        elif lms is None:
            mp["landmarks"] = []
        out["mp"] = mp

    # objdet — ודא מבנה בסיסי עם קיצוץ סביר
    od = out.get("objdet")
    if not isinstance(od, dict):
        od = {
            "frame": {"w": None, "h": None, "mirrored": False, "ts_ms": out["ts_ms"]},
            "objects": [],
            "tracks": [],
            "detector_state": {"ok": False, "err": "no_detection_engine", "provider": "none", "fps": 0.0},
        }
    else:
        objs = od.get("objects")
        if isinstance(objs, list) and len(objs) > _MAX_OBJECTS:
            od["objects"] = objs[:_MAX_OBJECTS]
        trks = od.get("tracks")
        if isinstance(trks, list) and len(trks) > _MAX_TRACKS:
            od["tracks"] = trks[:_MAX_TRACKS]
        od.setdefault("frame", {"w": None, "h": None, "mirrored": False, "ts_ms": out["ts_ms"]})
        od.setdefault("detector_state", {"ok": False, "err": None, "provider": "unknown", "fps": 0.0})
    out["objdet"] = od

    return out


def set_payload(payload: Dict[str, Any]) -> None:
    """
    שומר בזיכרון את הפיילוד האחרון שהגיע מהמנוע.
    • Thread-safe
    • עושה deepcopy כדי למנוע שינוי מבחוץ
    """
    if not isinstance(payload, dict):
        return
    safe = _sanitize_payload(payload)
    snap = deepcopy(safe)
    with _payload_lock:
        globals()["_last_payload"] = snap
    if _HAS_LOGGER:
        try:
            logger.debug(f"[STATE:set_payload] ts_ms={snap.get('ts_ms')} view={snap.get('view_mode')}")
        except Exception:
            pass


def get_payload() -> Dict[str, Any]:
    """מחזיר deepcopy של המצב האחרון (אי-אפשר לשנות לנו את הזיכרון בטעות)."""
    with _payload_lock:
        snap = deepcopy(_last_payload)
    if _HAS_LOGGER:
        try:
            logger.debug(f"[STATE:get_payload] has={bool(snap)} ts_ms={snap.get('ts_ms')}")
        except Exception:
            pass
    return snap


# =============================================================================
# 2) LOGS — מאגר טבעתי של לוגים ל-/api/logs
# =============================================================================

_LOGS_MAXLEN = int(os.getenv("ADMIN_LOGS_MAXLEN", "4000"))
_logs = deque(maxlen=max(100, _LOGS_MAXLEN))
_log_lock = Lock()


def add_log(level: str, module: str, msg: str, ts: Optional[float] = None) -> None:
    rec = {
        "ts": time() if ts is None else float(ts),
        "level": (level or "INFO").upper(),
        "module": str(module or ""),
        "msg": str(msg or ""),
    }
    with _log_lock:
        _logs.append(rec)


def get_logs(limit: int = 500, level_min: str = "INFO") -> List[Dict[str, Any]]:
    order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    try:
        min_idx = order.index((level_min or "INFO").upper())
    except ValueError:
        min_idx = 1  # INFO
    with _log_lock:
        data = list(_logs)
    filtered = [r for r in data if order.index(r.get("level", "INFO")) >= min_idx]
    return filtered[-max(1, int(limit)) :]


def clear_logs() -> None:
    with _log_lock:
        _logs.clear()


def get_logs_since(since_ts: float, level_min: str = "DEBUG") -> List[Dict[str, Any]]:
    order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    try:
        min_idx = order.index((level_min or "DEBUG").upper())
    except ValueError:
        min_idx = 0
    with _log_lock:
        data = [r for r in _logs if r["ts"] > float(since_ts)]
    return [r for r in data if order.index(r.get("level", "INFO")) >= min_idx]


# =============================================================================
# 3) Object Detection Engine Bridge — גשר למנוע OD חי (אם מחובר)
# =============================================================================

_od_engine: Optional[Any] = None
_od_lock = Lock()

_PRESET2IMGSZ = {"320p": 320, "384p": 384, "416p": 416, "480p": 480, "640p": 640}


def set_od_engine(engine: Any) -> None:
    """
    שמירת רפרנס למנוע ה-OD כדי שהשרת יוכל לקרוא/לעדכן.
    המנוע צפוי לספק: get_runtime_params(), update_simple(patch:dict) / get_simple()
    """
    with _od_lock:
        globals()["_od_engine"] = engine
    if _HAS_LOGGER:
        try:
            name = getattr(engine, "name", None) or getattr(getattr(engine, "detector_cfg", object()), "provider", "unknown")
            logger.info(f"[STATE:set_od_engine] hooked provider={name}")
        except Exception:
            pass


def get_od_engine():
    """מחזיר את המנוע אם קיים, אחרת None (לא זורק חריגות)."""
    with _od_lock:
        return _od_engine


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


def get_od_snapshot() -> Dict[str, Any]:
    """
    מחזיר צילום מצב 'נוח ל-UI' של מנוע ה-OD אם מחובר:
      { running, error, provider, device, imgsz, conf, iou, fps }
    אם אין מנוע — מחזיר מצב ברירת מחדל.
    """
    eng = get_od_engine()
    if eng is None:
        return {
            "running": False, "error": "no_engine", "provider": "none",
            "device": "cpu", "imgsz": 640, "conf": 0.15, "iou": 0.50, "fps": 0.0
        }
    try:
        rp = {}
        try:
            rp = eng.get_runtime_params() or {}
        except Exception:
            pass
        if not isinstance(rp, dict) or not rp:
            try:
                rp = eng.get_simple() or {}
            except Exception:
                rp = {}

        provider = rp.get("profile") or rp.get("provider") or getattr(getattr(eng, "detector_cfg", object()), "provider", "unknown")
        device   = rp.get("device") or getattr(getattr(eng, "detector_cfg", object()), "device", "cpu")
        conf     = float(rp.get("confidence_threshold", 0.15)) if _finite(rp.get("confidence_threshold", 0.15)) else 0.15
        iou      = float(rp.get("overlap", 0.50)) if _finite(rp.get("overlap", 0.50)) else 0.50
        preset   = rp.get("input_size")
        imgsz    = _PRESET2IMGSZ.get(str(preset), getattr(getattr(eng, "detector_cfg", object()), "extra", {}).get("imgsz", 640))
        fps      = float(rp.get("fps", 0.0)) if _finite(rp.get("fps", 0.0)) else 0.0

        return {
            "running": True, "error": "",
            "provider": provider, "device": device,
            "imgsz": int(imgsz) if isinstance(imgsz, (int, float)) else 640,
            "conf": conf, "iou": iou, "fps": round(fps, 2),
        }
    except Exception as e:
        if _HAS_LOGGER:
            logger.warning(f"[STATE:get_od_snapshot] failed: {e}")
        return {
            "running": False, "error": str(e), "provider": "unknown",
            "device": "cpu", "imgsz": 640, "conf": 0.15, "iou": 0.50, "fps": 0.0
        }


# =============================================================================
# 4) Lightweight OD Status — לוח סטטוס מהיר ל-UI
# =============================================================================

_od_status: Dict[str, Any] = {
    "enabled": False,      # האם מנוע OD פעיל כרגע
    "fps": 0.0,            # קצב יעד/ריצה (למשל 1000/period_ms)
    "latency_ms": 0,       # זמן עיבוד טיפוסי לטיק האחרון
    "count": 0,            # כמה טיקים/אינפרנסים בוצעו
    "provider": "unknown", # ספק/מודל (yolov8/...)
    "last_update_ts": 0.0, # זמן עדכון אחרון (epoch)
}
_od_status_lock = Lock()


def update_od_status(patch: Dict[str, Any]) -> None:
    """
    מעדכן את סטטוס ה-OD עבור ה-UI. קריאות תכופות מותרות.
    שדות נתמכים:
      • enabled: bool
      • fps: float/int
      • latency_ms: int/float
      • count_inc: int (נוסיף לערך count)
      • provider: str
    """
    if not isinstance(patch, dict):
        return
    now = time()
    with _od_status_lock:
        if "enabled" in patch:
            _od_status["enabled"] = bool(patch["enabled"])
        if "fps" in patch and _finite(patch["fps"]):
            _od_status["fps"] = float(patch["fps"])
        if "latency_ms" in patch and _finite(patch["latency_ms"]):
            _od_status["latency_ms"] = int(float(patch["latency_ms"]))
        if "count_inc" in patch and _finite(patch["count_inc"]):
            _od_status["count"] = int(_od_status.get("count", 0)) + int(patch["count_inc"])
        if "provider" in patch and isinstance(patch["provider"], str):
            _od_status["provider"] = patch["provider"] or _od_status.get("provider", "unknown")
        _od_status["last_update_ts"] = now


def get_od_status() -> Dict[str, Any]:
    """מצב ל-UI. אם לא עודכן לאחרונה — מחזירים את המצב כפי שהוא (stale זה בסדר לתצוגה)."""
    with _od_status_lock:
        return dict(_od_status)


# =============================================================================
# 5) Generic Frame Buffer (RGB) — חיבור גמיש לכל שיטת צילום
# =============================================================================
# שימוש:
# • routes_video.py (דפדפן) מפענח JPEG→RGB np.ndarray וקורא push_frame_np(frame).
# • מקור אחר (קובץ/RTSP/כל דבר) פשוט יקרא push_frame_np עם np.ndarray.
# • מנוע הזיהוי מושך get_frame()/is_frame_ready() — בלי לדעת מה המקור.

from typing import Optional as _Optional
import threading as _threading
import time as _time

try:
    import numpy as _np  # לטיפוסים; אם לא קיים אין כשל — פשוט לא נבדוק טיפוס
except Exception:
    _np = None  # type: ignore

_FRAME_LOCK = _threading.Lock()
_LAST_FRAME = None  # type: ignore  # np.ndarray | None
_LAST_PUSH_TS: float = 0.0
_FRAME_PROVIDER: str = "unknown"


def set_frame_provider_name(name: str) -> None:
    """שם ידידותי למקור הפריימים (לוגים/סטטוס): 'browser'/'file'/'rtsp'/..."""
    global _FRAME_PROVIDER
    with _FRAME_LOCK:
        _FRAME_PROVIDER = str(name or "unknown")


def get_frame_provider_name() -> str:
    with _FRAME_LOCK:
        return _FRAME_PROVIDER


def push_frame_np(frame) -> None:
    """
    שומר פריים RGB כ-np.ndarray (H,W,3, uint8).
    אין המרה/בדיקה יקרה — האחריות על הקורא.
    """
    global _LAST_FRAME, _LAST_PUSH_TS
    with _FRAME_LOCK:
        _LAST_FRAME = frame
        _LAST_PUSH_TS = _time.time()


def get_frame() -> _Optional["__import__('numpy').ndarray"]:  # טיפוס ידידותי לעורכים
    with _FRAME_LOCK:
        return _LAST_FRAME


def is_frame_ready(stale_secs: float = 3.0) -> bool:
    """האם יש פריים “טרי” (דחוף ב-stale_secs האחרונות)?"""
    with _FRAME_LOCK:
        if _LAST_FRAME is None:
            return False
        return (_time.time() - _LAST_PUSH_TS) <= stale_secs
