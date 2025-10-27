# -*- coding: utf-8 -*-
"""
app/ui/video_metrics_worker.py — Metrics מהפריים האחרון (PIL בלבד)
- משתמש ב-VideoStreamer.get_latest_jpeg()
- מחשב brightness פשוט (ממוצע ערוץ L)
- רץ רק אם VIDEO_METRICS_WORKER=1
"""

from __future__ import annotations
import os, threading, time, traceback
from typing import Dict, Any, Optional
from io import BytesIO

try:
    from PIL import Image, ImageStat  # type: ignore
    PIL_OK = True
except Exception:
    Image = None  # type: ignore
    ImageStat = None  # type: ignore
    PIL_OK = False

from app.ui.video import get_streamer

try:
    from admin_web.state import get_payload as _get_shared, set_payload as _set_shared  # type: ignore
except Exception:
    def _get_shared() -> Dict[str, Any]: return {}
    def _set_shared(_p: Dict[str, Any]) -> None: pass

ENABLED = (os.getenv("VIDEO_METRICS_WORKER", "0") == "1")

_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_STOP = False

def _analyze_jpeg(jpeg: bytes) -> Dict[str, Any]:
    if not (jpeg and PIL_OK):
        return {}
    try:
        with Image.open(BytesIO(jpeg)) as im:  # type: ignore
            w, h = im.size
            l = im.convert("L")
            stat = ImageStat.Stat(l)  # type: ignore
            brightness = float(stat.mean[0]) if stat and stat.mean else 0.0
            return {
                "video.width":  w,
                "video.height": h,
                "video.brightness": round(brightness, 2),
            }
    except Exception:
        return {}

def _merge_metrics_only(extra: Dict[str, Any]) -> None:
    base = _get_shared() or {}
    m = base.get("metrics")
    if not isinstance(m, dict):
        m = {}
    m.update(extra or {})
    base["metrics"] = m
    base.setdefault("ts", time.time())
    base.setdefault("payload_version", base.get("payload_version", "1.2.0"))
    _set_shared(base)

def _loop(interval: float = 0.25):
    s = get_streamer()
    last_seen_id = None
    while not _WORKER_STOP:
        try:
            jpeg = s.get_latest_jpeg()
            if jpeg:
                metrics = _analyze_jpeg(jpeg)
                if metrics:
                    _merge_metrics_only(metrics)
        except Exception:
            traceback.print_exc()
        time.sleep(interval)

def start_video_metrics_worker() -> bool:
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
    global _WORKER_STOP, _WORKER_THREAD
    _WORKER_STOP = True
    t = _WORKER_THREAD
    if t is not None and t.is_alive():
        t.join(timeout=timeout)
    _WORKER_THREAD = None

def is_video_metrics_worker_running() -> bool:
    return (_WORKER_THREAD is not None) and _WORKER_THREAD.is_alive()
