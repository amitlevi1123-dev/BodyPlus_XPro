# -*- coding: utf-8 -*-
"""
admin_web/routes_video.py — וידאו: ingest מהדפדפן + סטרים MJPEG + סטטוס
-----------------------------------------------------------------------
Endpoints:
- GET  /video/stream.mjpg        — סטרים MJPEG מתוך הזיכרון (ingest בלבד; לא מפעיל מקור)
- POST /api/ingest_frame         — קבלת JPEG מהדפדפן/טלפון (raw או multipart)
- GET  /api/video/status         — אינדיקציות מצב (camera/file, opened, running, fps, size, payload_age_sec, ffmpeg)
- POST /api/video/stop           — עצירת מקור פעיל (file/camera) עם לוגים ברורים

הערות:
- אין שימוש ב-OpenCV. הכל מבוסס JPEG ingest.
- אם routes_upload_video קיים, נשלוף ממנו מצב FFmpeg וסוג מקור ("file" / "camera").
- **חשוב:** לא מפעילים מקור וידאו אוטומטית כשנכנסים ל-/video/stream.mjpg.
"""

from __future__ import annotations
import os
import time
import json
from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Response, jsonify, request, stream_with_context

# ===== Logger =====
try:
    from core.logs import logger  # type: ignore
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("routes_video")

# ===== Video streamer (ingest-only) =====
try:
    from app.ui.video import get_streamer  # type: ignore
except Exception as e:
    get_streamer = None  # type: ignore
    logger.error("❌ cannot import app.ui.video.get_streamer: %r", e)

video_bp = Blueprint("video", __name__)

# ===== Optional integrations (upload-from-file via FFmpeg) =====
_HAS_UPLOAD = False
_get_stream_mode = None

try:
    # get_stream_mode() מחזיר "file" אם ffmpeg פעיל
    from admin_web.routes_upload_video import get_stream_mode as _gsm  # type: ignore
    _get_stream_mode = _gsm
    _HAS_UPLOAD = True
    logger.info("[video] routes_upload_video detected (get_stream_mode available)")
except Exception:
    logger.info("[video] routes_upload_video not present; file-mode will be unavailable")

_LOCAL_BASE = os.getenv("SERVER_BASE_URL", "http://127.0.0.1:5000").rstrip("/")


# ========================= Utilities =========================

def _read_request_bytes() -> Optional[bytes]:
    """
    קורא את גוף הבקשה כ-bytes. תומך גם ב-multipart (field: 'frame').
    """
    # multipart
    try:
        if request.files:
            f = request.files.get("frame")
            if f and hasattr(f, "read"):
                b = f.read()
                return b if b and len(b) > 10 else None
    except Exception:
        pass

    # raw binary
    try:
        data = request.get_data(cache=False)
        if data and len(data) > 10:
            return bytes(data)
    except Exception:
        pass
    return None


def _safe_json(obj: Any, default: str = "{}") -> str:
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return default


def _get_payload_age_sec() -> Optional[float]:
    """
    מחזיר גיל payload (בשניות) אם זמין.
    בודק admin_web.state.get_payload ואם לא — מנסה server.LAST_PAYLOAD.
    """
    now = time.time()
    # shared
    try:
        from admin_web.state import get_payload as _get_shared  # type: ignore
        pay = _get_shared() or {}
        if isinstance(pay, dict) and "ts" in pay:
            try:
                return max(0.0, now - float(pay["ts"]))
            except Exception:
                pass
    except Exception:
        pass

    # local LAST_PAYLOAD
    try:
        from server import LAST_PAYLOAD  # type: ignore
        pay2 = LAST_PAYLOAD or {}
        if isinstance(pay2, dict) and "ts" in pay2:
            try:
                return max(0.0, now - float(pay2["ts"]))
            except Exception:
                pass
    except Exception:
        pass
    return None


def _current_mode() -> str:
    """
    'file' אם routes_upload_video קיים ויש ffmpeg רץ, אחרת 'camera' (ingest).
    """
    try:
        if callable(_get_stream_mode):
            m = _get_stream_mode()
            if m in ("file", "camera"):
                return m
    except Exception:
        pass
    return "camera"


def _stop_file_mode_via_http() -> Tuple[bool, str]:
    """
    שולח POST פנימי ל-/api/video/stop_file כדי לעצור סטרים מקובץ (אם פעיל).
    """
    import urllib.request
    url = f"{_LOCAL_BASE}/api/video/stop_file"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            ok = (r.status == 200)
            return ok, f"stop_file HTTP status={r.status}"
    except Exception as e:
        return False, f"stop_file error: {e!r}"


# ========================= Routes =========================

@video_bp.get("/video/stream.mjpg")
def video_stream_mjpg():
    """
    סטרים MJPEG מתוך הזיכרון (ingest). **לא מפעיל מקור**.
    אם אין producer פעיל/אין פריימים — מחזיר 503 ולא מתחיל מצלמה.
    """
    if get_streamer is None:
        logger.error("❌ stream.mjpg requested but get_streamer is unavailable")
        return Response('{"ok":false,"error":"streamer_unavailable"}\n',
                        status=500, mimetype="application/json")

    s = get_streamer()

    # ── בלם Auto-Start: נבדוק אם יש מקור פעיל/פריימים בלי להפעיל כלום ──
    try:
        has_frames = False
        if hasattr(s, "buffer_len") and callable(getattr(s, "buffer_len")):
            try:
                has_frames = (s.buffer_len() or 0) > 0
            except Exception:
                has_frames = False
        is_running = False
        if hasattr(s, "is_running") and callable(getattr(s, "is_running")):
            try:
                is_running = bool(s.is_running())
            except Exception:
                is_running = False
        elif hasattr(s, "running"):
            is_running = bool(getattr(s, "running", False))

        if not (has_frames or is_running):
            logger.warning("[video] /video/stream.mjpg requested but no active producer (ingest mode)")
            return Response('{"ok":false,"error":"no_active_producer"}\n',
                            status=503, mimetype="application/json")
    except Exception:
        logger.debug("[video] status probe failed; assuming inactive")
        return Response('{"ok":false,"error":"inactive_streamer"}\n',
                        status=503, mimetype="application/json")

    # יש מקור פעיל → אפשר להזרים
    try:
        src_desc = getattr(s, "source_desc", lambda: "?")()
    except Exception:
        src_desc = "?"
    logger.info(f"[video] /video/stream.mjpg opened; source={src_desc}")

    def _gen():
        try:
            for chunk in s.get_jpeg_generator():  # לא יפעיל מקור אם כבר רץ
                yield chunk
        except GeneratorExit:
            logger.info("[video] client disconnected from /video/stream.mjpg")
        except Exception:
            logger.exception("[video] stream generator error")

    boundary = "frame"
    resp = Response(stream_with_context(_gen()),
                    mimetype=f"multipart/x-mixed-replace; boundary={boundary}")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@video_bp.post("/api/ingest_frame")
def api_ingest_frame():
    """
    ingest JPEG (raw או multipart field='frame').
    אופציונלי: X-Ingest-Token לכפילות עתידית (כרגע לא נבדק אם לא סופק).
    """
    token = request.headers.get("X-Ingest-Token", "")
    _len_hint = request.headers.get("Content-Length", "unknown")

    b = _read_request_bytes()
    if (b is None) or (len(b) < 10):
        logger.warning("⚠️ ingest_frame: empty/invalid body (len_hint=%s, token=%s)", _len_hint, "*" * len(token))
        return jsonify(ok=False, error="empty_or_invalid"), 400

    if get_streamer is None:
        logger.error("❌ ingest_frame: get_streamer is unavailable")
        return jsonify(ok=False, error="streamer_unavailable"), 500

    try:
        s = get_streamer()
        s.ingest_jpeg(b)
        logger.debug("ingest_frame: %d bytes | fps=~%s | size=%s",
                     len(b), getattr(s, "last_fps", lambda: None)(), getattr(s, "last_frame_size", lambda: None)())
        return jsonify(ok=True), 200
    except Exception:
        logger.exception("❌ ingest_frame exception")
        return jsonify(ok=False, error="ingest_failed"), 500


@video_bp.get("/api/video/status")
def api_video_status():
    """
    סטטוס וידאו מאוחד:
    - mode: 'file' (סטרים מקובץ) או 'camera' (ingest)
    - opened/running/fps/size: ממצב הסטרימר (ingest)
    - payload_age_sec: גיל payload האחרון (אם יש)
    - ffmpeg: אם routes_upload_video קיים — אינדיקציה בסיסית
    """
    out: Dict[str, Any] = {
        "ok": True,
        "mode": _current_mode(),
        "opened": False,
        "running": False,
        "fps": 0.0,
        "size": [0, 0],
        "payload_age_sec": None,
        "ffmpeg": None,
        "ts": time.time(),
    }

    # ingest streamer info
    try:
        if get_streamer:
            s = get_streamer()
            try:
                out["opened"] = bool(getattr(s, "is_open", lambda: False)())
            except Exception:
                out["opened"] = bool(getattr(s, "opened", False))
            try:
                out["running"] = bool(getattr(s, "is_running", lambda: False)())
            except Exception:
                out["running"] = bool(getattr(s, "running", False))
            try:
                fps = getattr(s, "last_fps", lambda: 0.0)() or 0.0
                out["fps"] = float(fps)
            except Exception:
                pass
            try:
                wh = getattr(s, "last_frame_size", lambda: (0, 0))() or (0, 0)
                out["size"] = [int(wh[0]), int(wh[1])]
            except Exception:
                pass
    except Exception:
        logger.exception("❌ api_video_status: streamer info failed")

    # payload age
    try:
        out["payload_age_sec"] = _get_payload_age_sec()
    except Exception:
        pass

    # ffmpeg indication (basic)
    if _HAS_UPLOAD:
        try:
            from admin_web.routes_upload_video import _ffmpeg_available, FFMPEG_BIN  # type: ignore
            out["ffmpeg"] = {"available": bool(_ffmpeg_available()), "bin": FFMPEG_BIN}
        except Exception:
            out["ffmpeg"] = {"available": False, "bin": None}

    logger.debug("[video] status | mode=%s opened=%s running=%s fps=%.2f size=%s age=%s ffmpeg=%s",
                 out["mode"], out["opened"], out["running"], out["fps"], out["size"],
                 out["payload_age_sec"], _safe_json(out.get("ffmpeg")))

    return jsonify(out), 200


@video_bp.post("/api/video/stop")
def api_video_stop():
    """
    עוצר מקור פעיל:
    - אם מצב 'file' → קורא ל-/api/video/stop_file (HTTP פנימי) כדי לעצור ffmpeg וה-emitter.
    - אחרת (camera/ingest) → מקפיא את הסטרימר / מאפס ריצה (לוגי בלבד).
    """
    mode = _current_mode()
    logger.info("[video] stop requested | mode=%s", mode)

    # file-mode: עצירת ffmpeg
    if mode == "file" and _HAS_UPLOAD:
        ok, msg = _stop_file_mode_via_http()
        logger.info("[video] stop_file result: %s | %s", "OK" if ok else "FAIL", msg)
        return jsonify(ok=bool(ok), mode="file", detail=msg), (200 if ok else 500)

    # ingest/camera: אין capture בצד השרת — רק "עצירה לוגית"
    try:
        if get_streamer:
            s = get_streamer()
            try:
                s.stop_auto_capture()  # no-op ברוב מימושי ingest-only; נשאיר לתאימות
            except Exception:
                pass
        logger.info("[video] ingest stopped (logical)")
        return jsonify(ok=True, mode="camera", detail="ingest_stopped"), 200
    except Exception as e:
        logger.exception("❌ video stop exception")
        return jsonify(ok=False, mode="camera", error=str(e)), 500
