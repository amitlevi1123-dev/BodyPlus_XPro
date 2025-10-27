# -*- coding: utf-8 -*-
"""
admin_web/routes_video.py — וידאו: ingest מהדפדפן + תמיכה בסטרים מקובץ (FFmpeg)
-------------------------------------------------------------------------------
Endpoints:
- POST /api/ingest_frame          — קבלת JPEG מהדפדפן (camera via browser)
- GET  /video/stream.mjpg         — סטרים MJPEG: אם file פעיל -> מפנה ל-/video/stream_file.mjpg,
                                   אחרת מזרים מה-ingest
- GET  /api/video/status          — סטטוס מפורט (מצב, גודל, FPS, גיל payload, מצב FFmpeg אם קיים)
- POST /api/video/stop            — עצירת סטרים (אם פעיל file: מפנה ל-/api/video/stop_file)

הקובץ לא משתמש ב-OpenCV בכלל.
"""

from __future__ import annotations
import os, time, json, logging, math
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Response, jsonify, request, redirect

# לוגger
try:
    from core.logs import logger  # type: ignore
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("routes_video")

video_bp = Blueprint("video", __name__)

# סטרימר ingest-Only (ללא OpenCV)
from app.ui.video import get_streamer

# ffmpeg/file stream תמיכה (אופציונלי — אם blueprint של upload-video נטען)
_HAS_UPLOAD = False
_get_stream_mode = None
_ffmpeg_debug_info = None
_stop_file_endpoint = "/api/video/stop_file"
try:
    from admin_web.routes_upload_video import get_stream_mode as _gsm  # type: ignore
    _get_stream_mode = _gsm
    _HAS_UPLOAD = True
    try:
        from admin_web.routes_upload_video import ffmpeg_debug_info as _ffi  # type: ignore
        _ffmpeg_debug_info = _ffi
    except Exception:
        _ffmpeg_debug_info = None
except Exception:
    _HAS_UPLOAD = False

# payload משותף — לחישוב גיל/מצב
try:
    from admin_web.state import get_payload as _get_shared_payload  # type: ignore
except Exception:
    def _get_shared_payload() -> Dict[str, Any]:
        return {}

def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)

def _payload_age_sec() -> float:
    try:
        p = _get_shared_payload() or {}
        ts = p.get("ts")
        if _finite(ts):
            return max(0.0, time.time() - float(ts))
    except Exception:
        pass
    return -1.0  # לא ידוע

def _current_mode() -> str:
    """'file' אם מופעל FFmpeg מהקובץ (אם blueprint קיים), אחרת 'camera'."""
    if _HAS_UPLOAD and callable(_get_stream_mode):
        try:
            return str(_get_stream_mode())  # 'file' | 'camera'
        except Exception:
            return "camera"
    return "camera"

# ========================= Ingest API (דפדפן שולח JPEG) ======================

@video_bp.post("/api/ingest_frame")
def api_ingest_frame():
    """
    מקבל JPEG מהדפדפן:
    - Content-Type: image/jpeg  (גוף = bytes)
    - או multipart/form-data עם 'frame' (קובץ)
    """
    s = get_streamer()

    # multipart
    f = request.files.get("frame")
    if f:
        data = f.read()
    else:
        # raw
        data = request.get_data(cache=False)

    if not data or len(data) < 10:
        return jsonify(ok=False, error="empty_or_invalid_frame"), 400

    try:
        s.ingest_jpeg(data)
        return jsonify(ok=True, bytes=len(data)), 200
    except Exception as e:
        logger.exception("[ingest] failed")
        return jsonify(ok=False, error=str(e)), 500

# ============================== Stream (MJPEG) ================================

@video_bp.get("/video/stream.mjpg")
def video_stream_mjpeg():
    """
    אם מופעל מצב file (FFmpeg) — מבצע הפניה ל-/video/stream_file.mjpg.
    אחרת מזרים מה-ingest (הדפדפן מזרים פריימים אל /api/ingest_frame).
    """
    mode = _current_mode()
    if mode == "file":
        # 307 = שמירת שיטת הבקשה/גוף; פה זה GET אז זה בטוח.
        return redirect("/video/stream_file.mjpg", code=307)

    s = get_streamer()
    gen = s.get_jpeg_generator()
    resp = Response(gen, mimetype="multipart/x-mixed-replace; boundary=frame")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

# ============================== Status & Control ==============================

@video_bp.get("/api/video/status")
def api_video_status():
    """סטטוס לממשק: מצב נוכחי, opened/running, FPS, גודל, גיל payload, מצב FFmpeg (אם קיים)."""
    s = get_streamer()
    try:
        opened = bool(getattr(s, "is_open", lambda: False)())
    except Exception:
        opened = False
    try:
        running = bool(getattr(s, "is_running", lambda: False)())
    except Exception:
        running = False
    try:
        fps = float(getattr(s, "last_fps", lambda: 0.0)() or 0.0)
    except Exception:
        fps = 0.0
    try:
        size = getattr(s, "last_frame_size", lambda: (0, 0))() or (0, 0)
        w, h = int(size[0]), int(size[1])
    except Exception:
        w, h = 0, 0

    mode = _current_mode()
    age = _payload_age_sec()

    out: Dict[str, Any] = {
        "ok": True,
        "mode": mode,                          # 'camera' | 'file'
        "opened": opened,
        "running": running,
        "fps": round(fps, 2),
        "size": [w, h],
        "payload_age_sec": (round(age, 3) if age >= 0 else None),
        "hints": {
            "camera_stream": "/video/stream.mjpg",
            "file_stream": "/video/stream_file.mjpg" if _HAS_UPLOAD else None,
            "ffmpeg_debug": "/api/debug/ffmpeg" if _HAS_UPLOAD else None,
            "stop_file": _stop_file_endpoint if _HAS_UPLOAD else None,
        }
    }

    # מידע FFmpeg אם קיים
    if _HAS_UPLOAD and callable(_ffmpeg_debug_info):
        try:
            dbg = _ffmpeg_debug_info() or {}
            out["ffmpeg"] = {
                "available": bool(dbg.get("ok", False)),
                "resolved": dbg.get("resolved"),
                "head": dbg.get("head", [])[:3],
            }
        except Exception as e:
            out["ffmpeg"] = {"available": False, "error": str(e)}

    return jsonify(out), 200


@video_bp.post("/api/video/stop")
def api_video_stop():
    """
    עצירת סטרים:
    - אם מצב file פעיל: מפנה ל-/api/video/stop_file (שקיים ב-routes_upload_video).
    - אחרת: עוצר רק את הפלג הוויזואלי (מנקה סטטוס ריצה) — אין מה להרוג (ingest תלוי בלקוח).
    """
    mode = _current_mode()
    if mode == "file" and _HAS_UPLOAD:
        return redirect(_stop_file_endpoint, code=307)

    # מצב camera/ingest — אין process להרוג; נסמן "לא רץ"
    try:
        s = get_streamer()
        if hasattr(s, "stop_auto_capture"):
            s.stop_auto_capture()  # no-op בסטרימר הנוכחי, אך ישמור תאימות
        return jsonify(ok=True, stopped=True, mode="camera"), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
