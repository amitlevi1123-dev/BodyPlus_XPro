# -*- coding: utf-8 -*-
"""
app/ui/video_metrics_worker.py — מחבר את הווידאו למערכת המדידות (גרסה בטוחה)
-------------------------------------------------------------------------------
שינויים חשובים:
- לא דוחף payload חדש שדורס את הקיים.
- מבצע merge עדין רק לשדות metrics (תחת prefix 'video.*').
- לא שולח POST ולא קורא VideoStreamer.push_payload (מונע מריבות עם main).
- מוגדר כבוי כברירת מחדל; מפעילים רק אם VIDEO_METRICS_WORKER=1.
"""

from __future__ import annotations
import os, threading, time, traceback
from typing import Dict, Any, Optional

try:
    import cv2
    import numpy as np
    CV2_OK = True
except Exception:
    cv2 = None  # type: ignore
    np = None   # type: ignore
    CV2_OK = False

# מקור הפריים (לא משתמשים ב-push_payload שלו)
from app.ui.video import get_streamer

# גישה ל-state המשותף כדי לבצע merge עדין
try:
    from admin_web.state import get_payload as _get_shared, set_payload as _set_shared  # type: ignore
except Exception:
    def _get_shared() -> Dict[str, Any]: return {}
    def _set_shared(_p: Dict[str, Any]) -> None: pass

# הפעלה רק אם רוצים במפורש
ENABLED = (os.getenv("VIDEO_METRICS_WORKER", "0") == "1")

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = False


def _analyze_frame(frame) -> Dict[str, Any]:
    """מדידות בסיסיות בלבד, לא מחזיר מבנה payload — רק metrics."""
    h = w = None
    brightness = 0.0
    try:
        if frame is not None and CV2_OK:
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            brightness = float(gray.mean())
    except Exception:
        pass

    return {
        "video.width":  w or 0,
        "video.height": h or 0,
        "video.brightness": round(brightness, 2),
    }


def _merge_metrics_only(extra_metrics: Dict[str, Any]) -> None:
    """
    מביא payload קיים מה־RAM (admin_web.state), ממזג רק metrics, ושומר.
    לא נוגע ב-objdet/mp/detections/וכו'.
    """
    base = _get_shared() or {}
    m = base.get("metrics")
    if not isinstance(m, dict):
        m = {}
    # merge עדין:
    for k, v in (extra_metrics or {}).items():
        m[k] = v
    base["metrics"] = m
    # חותמת זמן עדינה
    base.setdefault("ts", time.time())
    base.setdefault("payload_version", base.get("payload_version", "1.2.0"))
    _set_shared(base)


def _loop(interval: float = 0.1):
    s = get_streamer()
    while not _WORKER_STOP:
        try:
            ok, frame = s.read_frame()
            if ok and frame is not None:
                metrics = _analyze_frame(frame)
                _merge_metrics_only(metrics)
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def start_video_metrics_worker() -> bool:
    """מפעיל worker רק אם ENABLED=True, ורק פעם אחת."""
    global _WORKER_THREAD, _WORKER_STOP
    if not ENABLED:
        return False
    if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
        return True
    _WORKER_STOP = False
    t = threading.Thread(target=_loop, name="video_metrics_worker", daemon=True)
    _WORKER_THREAD = t
    t.start()
    return True


def stop_video_metrics_worker(timeout: float = 1.5) -> None:
    """מפסיק את ה־worker ומחכה לסיום נקי."""
    global _WORKER_STOP, _WORKER_THREAD
    _WORKER_STOP = True
    t = _WORKER_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    _WORKER_THREAD = None


def is_video_metrics_worker_running() -> bool:
    """בודק אם ה־worker פעיל כרגע."""
    return (_WORKER_THREAD is not None) and _WORKER_THREAD.is_alive()
