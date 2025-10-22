# -*- coding: utf-8 -*-
"""
routes_video.py — Video API נקי ועמיד למירוצים (ללא VideoManager)

נקודות קצה:
- POST /api/video/start
- POST /api/video/stop
- GET  /api/video/status
- GET  /video/stream.mjpg
- GET  /video/stream

שליטה ידנית:
- GET  /api/camera/settings
- POST /api/camera/settings

אקסטרות לשליטה ישירה ב־VideoStreamer:
- POST /api/video/preview
- POST /api/video/freeze
- POST /api/video/unfreeze
- GET  /api/video/capabilities

[NEW]
- GET/POST /api/video/params        : קבלת/עדכון jpeg_quality, encode_fps, target_fps, decimation, או פרופיל Eco/Balanced/Quality
- POST     /api/video/resolution    : שינוי רזולוציה לפי preset: low/medium/high
"""

from __future__ import annotations
import os, time, logging
from typing import Callable, Tuple, Dict, Any

from flask import Blueprint, Response, jsonify, request, redirect, stream_with_context

# --- Logger ---
try:
    from core.logs import logger  # אם קיים
except Exception:
    logger = logging.getLogger("routes_video")

# --- Video source (VideoStreamer יחיד) ---
from app.ui.video import get_streamer

# --- אופציונלי: camera_controller כ־fallback (אם קיים) ---
try:
    from app.ui.camera_controller import (
        apply_settings as cc_apply,
        get_settings as cc_get,
        register_cap as cc_register,
    )
    _HAS_CC = True
except Exception:
    _HAS_CC = False

# --- מיקסר מקור: מצב "camera"/"file" מ-routes_upload_video (אם קיים) ---
try:
    from admin_web.routes_upload_video import get_stream_mode  # type: ignore
except Exception:
    def get_stream_mode() -> str:
        return "camera"

video_bp = Blueprint("video", __name__)

DEFAULT_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))

# ---------- Utilities ----------
def _wait_until(fn: Callable[[], bool], timeout_s: float = 2.0, interval_s: float = 0.05) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(interval_s)
    return False

def _try_close_all(s) -> None:
    for name in ("hard_close_camera", "close_camera", "release_camera", "release", "close", "shutdown"):
        try:
            fn = getattr(s, name, None)
            if callable(fn):
                fn()
        except Exception:
            pass

def _extract_settings_from_json(data: Dict[str, Any]) -> Tuple[int, int, int]:
    fps = int(data.get("fps", data.get("camera_fps", 15)))
    width = int(data.get("width", data.get("w", 1280)))
    height = int(data.get("height", data.get("h", 720)))
    return fps, width, height

def _clip_int(val, lo, hi, default):
    try:
        v = int(val)
    except Exception:
        return int(default)
    return int(max(lo, min(hi, v)))

# ---------- Endpoints: start/stop/status/stream ----------
@video_bp.route("/api/video/start", methods=["POST"])
def api_video_start():
    j = request.get_json(silent=True) or {}
    cam_idx = j.get("camera_index", DEFAULT_CAMERA_INDEX)
    show_preview = bool(j.get("show_preview", False))

    s = get_streamer()

    # עצור אם רץ, והמתן לסיום
    try:
        if s.is_running():
            try:
                s.stop_auto_capture()
            except Exception:
                pass
            _wait_until(lambda: not bool(s.is_running()), timeout_s=2.0, interval_s=0.05)
    except Exception:
        pass

    # אם עדיין פתוח/תקוע — סגירה קשיחה ושהות קצרה לשחרור הדרייבר
    try:
        if s.is_open():
            _try_close_all(s)
            time.sleep(0.2)
    except Exception:
        pass

    # עדכון מצלמה
    try:
        s.camera_index = int(cam_idx)
    except Exception:
        pass

    # הפעלה
    try:
        s.start_auto_capture()
        try:
            s.enable_preview(show_preview)
        except Exception:
            pass

        if _HAS_CC:
            try:
                get_cap = getattr(s, "get_cap", None)
                if callable(get_cap):
                    cap = get_cap()
                    if cap is not None:
                        w, h = 1280, 720
                        fps = 30
                        try:
                            size = s.last_frame_size() or (w, h)
                            if isinstance(size, (list, tuple)) and len(size) == 2:
                                w, h = int(size[0]), int(size[1])
                        except Exception:
                            pass
                        try:
                            v = s.last_fps() or fps
                            fps = int(v)
                        except Exception:
                            pass
                        cc_register(cap, source={"type": "camera", "index": int(cam_idx)},
                                    width=w, height=h, fps=fps)
            except Exception:
                pass

        return jsonify(ok=True, source=s.source_desc()), 200
    except Exception as e:
        logger.error("/api/video/start failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/stop", methods=["POST"])
def api_video_stop():
    s = get_streamer()
    try:
        try:
            s.stop_auto_capture()
        except Exception:
            pass
        _wait_until(lambda: not bool(s.is_running()), timeout_s=2.0, interval_s=0.05)
        try:
            if s.is_open():
                _try_close_all(s)
        except Exception:
            pass
        try:
            s.enable_preview(False)
        except Exception:
            pass
        return jsonify(ok=True), 200
    except Exception as e:
        logger.error("/api/video/stop failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/status", methods=["GET"])
def api_video_status():
    s = get_streamer()
    try:
        opened = bool(s.is_open())
        running = bool(s.is_running()) and opened
        size = s.last_frame_size()
        fps = s.last_fps()
        source = s.source_desc()
        try:
            light_mode = s.get_light_mode()
        except Exception:
            light_mode = None
        try:
            preview_window_open = bool(getattr(s, "_preview", False))
        except Exception:
            preview_window_open = False
        state = "ACTIVE"
        try:
            if bool(getattr(s, "_frozen", False)) or getattr(s, "_freeze_until", None):
                state = "FROZEN"
        except Exception:
            pass

        return jsonify(
            ok=True,
            opened=opened,
            running=running,
            fps=fps,
            size=size,
            source=source,
            light_mode=light_mode,
            preview_window_open=preview_window_open,
            state=state,
            error=None,
        ), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/video/stream.mjpg", methods=["GET"])
def video_stream_mjpg():
    try:
        if get_stream_mode() == "file":
            return redirect("/video/stream_file.mjpg", code=307)
    except Exception:
        pass

    s = get_streamer()

    try:
        if not (s.is_open() and s.is_running()):
            return jsonify(ok=False, error="stream_unavailable", reason="camera_not_running_or_not_open"), 503
    except Exception:
        return jsonify(ok=False, error="stream_unavailable", reason="status_error"), 503

    gen = getattr(s, "get_jpeg_generator", None)
    if not callable(gen):
        return jsonify(ok=False, error="jpeg_generator_not_available"), 503

    boundary = "frame"
    try:
        resp = Response(
            stream_with_context(gen()),
            mimetype=f"multipart/x-mixed-replace; boundary={boundary}",
        )
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp
    except Exception as e:
        logger.error("[video_stream_mjpg] error", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/video/stream", methods=["GET"])
def video_stream_legacy():
    return redirect("/video/stream.mjpg", code=302)

# ---------- Endpoints: camera settings (manual FPS + resolution) ----------
@video_bp.route("/api/camera/settings", methods=["GET"])
def api_camera_settings_get():
    s = get_streamer()
    try:
        g = getattr(s, "get_camera_settings", None)
        if callable(g):
            st = g()
            if isinstance(st, dict):
                return jsonify(ok=True, settings=st), 200
    except Exception:
        pass

    if _HAS_CC:
        try:
            return jsonify(ok=True, settings=cc_get()), 200
        except Exception:
            pass

    try:
        w, h = (1280, 720)
        try:
            size = s.last_frame_size() or (w, h)
            if isinstance(size, (tuple, list)) and len(size) == 2:
                w, h = int(size[0]), int(size[1])
        except Exception:
            pass
        fps = 30
        try:
            v = s.last_fps() or fps
            fps = int(v)
        except Exception:
            pass
        return jsonify(ok=True, settings={"fps": fps, "width": w, "height": h}), 200
    except Exception:
        return jsonify(ok=False, error="no_settings_available"), 503

@video_bp.route("/api/camera/settings", methods=["POST"])
def api_camera_settings_post():
    """
    JSON: { "fps": 15, "width": 1280, "height": 720 }
    קודם ננסה live-apply דרך ה-streamer; אם לא — נפעיל fallbackים.
    """
    data = request.get_json(silent=True) or {}
    fps, width, height = _extract_settings_from_json(data)
    s = get_streamer()

    # 1) apply דרך ה-streamer (עובד גם headless ומחזיר applied_headless)
    try:
        apply_fn = getattr(s, "apply_camera_settings", None)
        if callable(apply_fn):
            ok, msg = apply_fn(fps=fps, width=width, height=height)
            # במידה והוחל חלקית או צריך restart — נטפל בהמשך; אם ok=True מחזירים 200
            if ok:
                return jsonify(ok=True, message=msg,
                               settings={"fps": int(s.fps), "width": int(s.width), "height": int(s.height)}), 200
            # אם ביקש restart (live_apply_partial/need_restart) נמשיך ל־fallbackים למטה
    except Exception:
        pass

    # 2) camera_controller
    if _HAS_CC:
        try:
            ok, msg = cc_apply(fps=fps, width=width, height=height)
            return jsonify(ok=bool(ok), message=msg, settings=cc_get()), (200 if ok else 500)
        except Exception as e:
            logger.warning(f"camera_controller_failed: {e!r}")

    # 3) Restart נקי
    try:
        try:
            s.stop_auto_capture()
        except Exception:
            pass
        _wait_until(lambda: not bool(s.is_running()), timeout_s=2.0, interval_s=0.05)

        try: s.width = int(width)
        except Exception: pass
        try: s.height = int(height)
        except Exception: pass
        try: s.fps = int(fps)
        except Exception: pass

        try:
            if s.is_open():
                _try_close_all(s)
                time.sleep(0.2)
        except Exception:
            pass

        s.start_auto_capture()
        return jsonify(ok=True, message="restarted_with_new_params",
                       settings={"fps": int(s.fps), "width": int(s.width), "height": int(s.height)}), 200
    except Exception as e:
        logger.error("/api/camera/settings POST failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

# ---------- NEW: params (jpeg/קצבים/דילוג) ----------
@video_bp.route("/api/video/params", methods=["GET", "POST"])
def api_video_params():
    s = get_streamer()
    if request.method == "GET":
        try:
            out = {
                "jpeg_quality": int(getattr(s, "jpeg_quality", 70)),
                "encode_fps":   int(getattr(s, "encode_fps", 15)),
                "target_fps":   int(getattr(s, "target_fps", getattr(s, "fps", 30))),
                "decimation":   int(getattr(s, "_decimation", 1)),
            }
            return jsonify(ok=True, params=out), 200
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    # POST
    j = request.get_json(silent=True) or {}
    profile = (j.get("profile") or "").strip().lower()

    # פרופילים מוכנים
    profiles = {
        "eco":      {"jpeg_quality": 55, "encode_fps": 8,  "target_fps": 10, "decimation": 2},
        "balanced": {"jpeg_quality": 70, "encode_fps": 12, "target_fps": 20, "decimation": 1},
        "quality":  {"jpeg_quality": 85, "encode_fps": 15, "target_fps": 30, "decimation": 1},
    }
    if profile in profiles:
        p = profiles[profile]
        try: s.jpeg_quality = int(p["jpeg_quality"])
        except Exception: pass
        try: s.encode_fps   = int(p["encode_fps"])
        except Exception: pass
        try: s.target_fps   = int(p["target_fps"])
        except Exception: pass
        try: s.set_decimation(int(p["decimation"]))
        except Exception: pass
        return jsonify(ok=True, applied="profile", profile=profile, params=p), 200

    # ידני
    try:
        if "jpeg_quality" in j:
            s.jpeg_quality = _clip_int(j["jpeg_quality"], 40, 95, getattr(s, "jpeg_quality", 70))
        if "encode_fps" in j:
            s.encode_fps   = _clip_int(j["encode_fps"],   0, 60, getattr(s, "encode_fps", 15))
        if "target_fps" in j:
            s.target_fps   = _clip_int(j["target_fps"],   0, 60, getattr(s, "target_fps", getattr(s, "fps", 30)))
        if "decimation" in j:
            s.set_decimation(_clip_int(j["decimation"],   1, 8, 1))
        out = {
            "jpeg_quality": int(getattr(s, "jpeg_quality", 70)),
            "encode_fps":   int(getattr(s, "encode_fps", 15)),
            "target_fps":   int(getattr(s, "target_fps", getattr(s, "fps", 30))),
            "decimation":   int(getattr(s, "_decimation", 1)),
        }
        return jsonify(ok=True, applied="manual", params=out), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

# ---------- NEW: resolution presets ----------
@video_bp.route("/api/video/resolution", methods=["POST"])
def api_video_resolution():
    """
    JSON: { "preset": "low"|"medium"|"high" } או { "width": 1280, "height": 720 }
    """
    s = get_streamer()
    j = request.get_json(silent=True) or {}
    preset = (j.get("preset") or "").strip().lower()

    if preset:
        if preset == "low":
            width, height = 640, 360
        elif preset == "medium":
            width, height = 1280, 720
        elif preset == "high":
            width, height = 1920, 1080
        else:
            return jsonify(ok=False, error="unknown_preset"), 400
    else:
        try:
            width  = int(j.get("width"))
            height = int(j.get("height"))
        except Exception:
            return jsonify(ok=False, error="bad_width_height"), 400

    # העדפה ל־apply_camera_settings (עובד גם headless)
    try:
        apply_fn = getattr(s, "apply_camera_settings", None)
        if callable(apply_fn):
            ok, msg = apply_fn(width=width, height=height)
            if ok:
                return jsonify(ok=True, message=msg, width=int(s.width), height=int(s.height)), 200
    except Exception:
        pass

    # fallback: עדכון שדות + restart נקי
    try:
        try: s.stop_auto_capture()
        except Exception: pass
        _wait_until(lambda: not bool(s.is_running()), timeout_s=2.0, interval_s=0.05)

        try: s.width = int(width)
        except Exception: pass
        try: s.height = int(height)
        except Exception: pass

        try:
            if s.is_open():
                _try_close_all(s)
                time.sleep(0.2)
        except Exception:
            pass

        s.start_auto_capture()
        return jsonify(ok=True, message="restarted_with_new_resolution",
                       width=int(s.width), height=int(s.height)), 200
    except Exception as e:
        logger.error("/api/video/resolution failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

# ---------- Extras: preview/freeze/capabilities ----------
@video_bp.route("/api/video/preview", methods=["POST"])
def api_video_preview():
    s = get_streamer()
    j = request.get_json(silent=True) or {}
    on = bool(j.get("on", True))
    try:
        s.enable_preview(on)
        return jsonify(ok=True, preview_window_open=bool(getattr(s, "_preview", False))), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/freeze", methods=["POST"])
def api_video_freeze():
    s = get_streamer()
    j = request.get_json(silent=True) or {}
    secs = float(j.get("seconds", 0))
    try:
        if secs and secs > 0:
            s.freeze_for(secs)
        else:
            s.set_freeze(True)
        return jsonify(ok=True), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/unfreeze", methods=["POST"])
def api_video_unfreeze():
    s = get_streamer()
    try:
        s.set_freeze(False)
        return jsonify(ok=True), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/capabilities", methods=["GET"])
def api_video_capabilities():
    s = get_streamer()
    out: Dict[str, Any] = {
        "has_camera_controller": _HAS_CC,
        "supports_preview": hasattr(s, "enable_preview"),
        "supports_freeze": all(hasattr(s, n) for n in ("set_freeze", "freeze_for")),
        "supports_live_apply": hasattr(s, "apply_camera_settings"),
        "defaults": {
            "width": getattr(s, "width", 1280),
            "height": getattr(s, "height", 720),
            "fps": getattr(s, "fps", 30),
            "jpeg_quality": getattr(s, "jpeg_quality", 70),
            "encode_fps": getattr(s, "encode_fps", 15),
            "target_fps": getattr(s, "target_fps", getattr(s, "fps", 30)),
            "decimation": getattr(s, "_decimation", 1),
        },
        "source": s.source_desc(),
    }
    return jsonify(ok=True, capabilities=out), 200
