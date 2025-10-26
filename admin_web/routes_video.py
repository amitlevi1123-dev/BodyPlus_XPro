# -*- coding: utf-8 -*-
"""
routes_video.py — Video API נקי, עם ingest מהטלפון, HUD על הווידאו, ולוגים.
שומר תאימות ל-API הקיים + מוסיף:
- POST /api/ingest_frame          ← קליטת פריימים כ-JPEG (טלפון/דפדפן)
- Fallback חכם ב-/video/stream.mjpg כשה-Streamer לא רץ
- HUD (נתוני סטטוס) על הווידאו עצמו: fps/latency/size/source/time
- פרמטר ?hud=0/1 לסטרים (ברירת מחדל: HUD פעיל)

קיים מראש:
- POST /api/video/start, /api/video/stop, GET /api/video/status
- GET /video/stream.mjpg, GET /video/stream (legacy)
- GET/POST /api/camera/settings
- GET/POST /api/video/params
- POST /api/video/resolution
- POST /api/video/preview, /api/video/freeze, /api/video/unfreeze
- GET /api/video/capabilities
"""

from __future__ import annotations
import os, time, logging
from typing import Callable, Tuple, Dict, Any, Optional, Deque, Iterator
from collections import deque
from io import BytesIO

from flask import Blueprint, Response, jsonify, request, redirect, stream_with_context

# ---------- Logger ----------
try:
    from core.logs import logger  # אם קיים בפרויקט
except Exception:
    logger = logging.getLogger("routes_video")
    if not logger.handlers:
        _h = logging.StreamHandler()
        _fmt = logging.Formatter("[%(asctime)s] %(levelname)s routes_video: %(message)s")
        _h.setFormatter(_fmt)
        logger.addHandler(_h)
    logger.setLevel(logging.INFO)

# ---------- תלויות פנימיות ----------
# Video source (VideoStreamer יחיד)
from app.ui.video import get_streamer

# אופציונלי: camera_controller כ־fallback
try:
    from app.ui.camera_controller import (
        apply_settings as cc_apply,
        get_settings as cc_get,
        register_cap as cc_register,
    )
    _HAS_CC = True
except Exception:
    _HAS_CC = False

# מצב מקור "camera"/"file" (אם קיים)
try:
    from admin_web.routes_upload_video import get_stream_mode  # type: ignore
except Exception:
    def get_stream_mode() -> str:
        return "camera"

# ---------- Blueprint ----------
video_bp = Blueprint("video", __name__)

DEFAULT_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))

# ---------- Utils ----------
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

def _now_ms() -> int:
    return int(time.time() * 1000)

# ---------- Ingest (טלפון → שרת) + HUD ----------
from PIL import Image, ImageDraw, ImageFont  # Pillow

_BOUNDARY = b"--frame"

class _FPSMeter:
    """מדד FPS פשוט על חלון זמנים קצר."""
    def __init__(self, window_sec: float = 2.0):
        self.window = window_sec
        self.ts: Deque[float] = deque(maxlen=200)

    def tick(self) -> None:
        t = time.time()
        self.ts.append(t)
        # נפטר מטיימסטמפים ישנים
        while self.ts and (t - self.ts[0] > self.window):
            self.ts.popleft()

    def fps(self) -> float:
        if len(self.ts) < 2:
            return 0.0
        dt = max(1e-6, self.ts[-1] - self.ts[0])
        return (len(self.ts) - 1) / dt

class _IngestState:
    """מצב ingest של מצלמה אחת (פשוט להרחבה ל-multi-cam בעתיד)."""
    def __init__(self):
        self.jpeg: Optional[bytes] = None
        self.ts_ms: int = 0
        self.size: Optional[tuple[int,int]] = None
        self.rx_fps = _FPSMeter(window_sec=2.0)    # קצב פריימים נכנס
        self.enc_fps = _FPSMeter(window_sec=2.0)   # קצב קידוד/הגשה לסטרים

INGEST = _IngestState()

# פונט HUD (ניסיון לטעון פונט יפה; אם לא — ברירת מחדל)
def _load_font(size: int = 18) -> Optional[ImageFont.FreeTypeFont]:
    try:
        # אפשר למקם פונט משלך בפרויקט (למשל app/static/fonts/Heebo.ttf)
        font_paths = [
            "app/static/fonts/Heebo.ttf",
            "app/static/fonts/Arimo.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for p in font_paths:
            if os.path.exists(p):
                return ImageFont.truetype(p, size=size)
    except Exception:
        pass
    return None

_HUD_FONT = _load_font(18)

def _overlay_hud(jpeg_bytes: bytes, *, label: str, extra: Dict[str, Any]) -> bytes:
    """מצייר HUD על גבי JPEG (שקוף מספיק, לא פולשני)."""
    try:
        im = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
    except Exception:
        return jpeg_bytes

    W, H = im.size
    draw = ImageDraw.Draw(im)
    font = _HUD_FONT

    # בונים שורות מידע
    lines = [
        f"{label}",
        f"time: {time.strftime('%H:%M:%S')}",
    ]
    # extra: fps/lat/size/source/state...
    for k in ("ingest_fps", "encode_fps", "size", "lat_ms", "source", "state"):
        if k in extra:
            lines.append(f"{k}: {extra[k]}")

    # רקע: מלבן בפינה שמאלית-עליונה
    pad = 8
    line_h = 22 if font else 18
    box_w = int(10 + max((draw.textlength(l, font=font) if font else len(l)*9) for l in lines) + 2*pad)
    box_h = int(10 + line_h * len(lines) + 2*pad)
    x0, y0 = 10, 10
    x1, y1 = x0 + box_w, y0 + box_h
    draw.rectangle((x0, y0, x1, y1), fill=(0, 0, 0, 180))

    # טקסטים
    y = y0 + pad
    for i, l in enumerate(lines):
        color = (180, 220, 255) if i == 0 else (255, 255, 255)
        draw.text((x0 + pad, y), l, fill=color, font=font)
        y += line_h

    out = BytesIO()
    im.save(out, format="JPEG", quality=extra.get("jpeg_quality", 80))
    return out.getvalue()

def _process_ingest_frame(jpeg_bytes: bytes) -> bytes:
    """
    עיבוד אופציונלי לפריים נכנס (כאן לא נחייב עיבוד, רק נעדכן גודל/HUD בבקשה).
    את ה-HUD נוסיף בזמן ההגשה (generator) כדי לא לקודד פעמיים.
    """
    # עדכון גודל הפריים (לסטטוס)
    try:
        im = Image.open(BytesIO(jpeg_bytes))
        INGEST.size = im.size
    except Exception:
        pass
    return jpeg_bytes

@video_bp.post("/api/ingest_frame")
def api_ingest_frame():
    """
    קולט פריים בודד כ-JPEG:
    1) raw body עם Content-Type: image/jpeg
    2) או multipart/form-data עם שדה 'frame'
    """
    try:
        jpeg = None
        if request.content_type and "image/jpeg" in request.content_type.lower():
            jpeg = request.get_data()
        if jpeg is None and "frame" in request.files:
            jpeg = request.files["frame"].read()
        if not jpeg:
            return jsonify(ok=False, error="missing image/jpeg"), 400

        # (אופציונלי) בדיקת טוקן:
        # token = request.headers.get("X-Ingest-Token")
        # if REQUIRED_TOKEN and token != REQUIRED_TOKEN: return 401

        jpeg = _process_ingest_frame(jpeg)
        INGEST.jpeg = jpeg
        INGEST.ts_ms = _now_ms()
        INGEST.rx_fps.tick()

        return jsonify(ok=True, ts_ms=INGEST.ts_ms)
    except Exception as e:
        logger.error("api_ingest_frame failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

def _ingest_mjpeg_generator(hud: bool = True) -> Iterator[bytes]:
    """סטרים MJPEG מתוך ה-ingest (פריים אחרון)."""
    last_sent_ts = -1
    while True:
        if INGEST.jpeg is None:
            time.sleep(0.05)
            continue

        # אל תשלח פעמיים את אותו פריים אם אין חדש (מוריד רעש)
        if INGEST.ts_ms == last_sent_ts:
            time.sleep(0.01)
            continue

        frame = INGEST.jpeg
        extra = {
            "ingest_fps": f"{INGEST.rx_fps.fps():.1f}",
            "encode_fps": f"{INGEST.enc_fps.fps():.1f}",
            "size": f"{INGEST.size[0]}x{INGEST.size[1]}" if INGEST.size else "–",
            "lat_ms": (_now_ms() - INGEST.ts_ms),
            "source": "phone/capture",
            "state": "INGEST",
            "jpeg_quality": 80,
        }
        if hud:
            try:
                frame = _overlay_hud(frame, label="BodyPlus_XPro", extra=extra)
            except Exception:
                # אם נכשל ציור HUD — נשלח את המקור
                pass

        # עדכון FPS של ההגשה
        INGEST.enc_fps.tick()

        chunk = (
            _BOUNDARY + b"\r\n"
            + b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
            + frame + b"\r\n"
        )
        last_sent_ts = INGEST.ts_ms
        time.sleep(0.001)  # עדין מאוד — כמעט ללא השהיה
        yield chunk

# ---------- Endpoints: start/stop/status/stream ----------
@video_bp.route("/api/video/start", methods=["POST"])
def api_video_start():
    j = request.get_json(silent=True) or {}
    cam_idx = j.get("camera_index", DEFAULT_CAMERA_INDEX)
    show_preview = bool(j.get("show_preview", False))

    s = get_streamer()
    logger.info(f"/api/video/start requested (camera_index={cam_idx}, preview={show_preview})")

    # עצור אם רץ, והמתן לסיום
    try:
        if s.is_running():
            s.stop_auto_capture()
            _wait_until(lambda: not bool(s.is_running()), timeout_s=2.0, interval_s=0.05)
    except Exception:
        pass

    # אם עדיין פתוח/תקוע — סגירה קשיחה
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

        logger.info(f"/api/video/start OK — source={s.source_desc()}")
        return jsonify(ok=True, source=s.source_desc()), 200
    except Exception as e:
        logger.error("/api/video/start failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/api/video/stop", methods=["POST"])
def api_video_stop():
    s = get_streamer()
    logger.info("/api/video/stop requested")
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
        logger.info("/api/video/stop OK")
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

        # סטטוס ingest (טלפון) כתוספת שימושית למסכי ניהול
        ingest_state = {
            "has_frame": INGEST.jpeg is not None,
            "rx_fps": round(INGEST.rx_fps.fps(), 1),
            "enc_fps": round(INGEST.enc_fps.fps(), 1),
            "last_ts_ms": INGEST.ts_ms,
            "lat_ms": (_now_ms() - INGEST.ts_ms) if INGEST.ts_ms else None,
            "size": list(INGEST.size) if INGEST.size else None,
        }

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
            ingest=ingest_state,
            error=None,
        ), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.route("/video/stream.mjpg", methods=["GET"])
def video_stream_mjpg():
    """
    סטרים MJPEG:
    - אם מצב 'file' → מפנה ל-/video/stream_file.mjpg
    - אם ה-Streamer רץ → זורם ממנו
    - אחרת: אם יש ingest (טלפון) → זורם ממנו עם HUD
    פרמטרים:
      ?hud=1/0  הפעלת HUD (ברירת מחדל: 1)
    """
    hud = request.args.get("hud", "1").strip() != "0"

    try:
        if get_stream_mode() == "file":
            return redirect("/video/stream_file.mjpg", code=307)
    except Exception:
        pass

    s = get_streamer()

    try:
        # אם ה-Streamer לא פעיל — נסה ingest
        if not (s.is_open() and s.is_running()):
            if INGEST.jpeg is not None:
                logger.info("stream.mjpg: using INGEST fallback (streamer not running)")
                return _make_mjpeg_response(_ingest_mjpeg_generator(hud=hud))
            return jsonify(ok=False, error="stream_unavailable", reason="camera_not_running_or_not_open"), 503
    except Exception:
        # שגיאת סטטוס ב-Streamer → נסה ingest
        if INGEST.jpeg is not None:
            logger.warning("stream.mjpg: streamer status error — fallback to INGEST")
            return _make_mjpeg_response(_ingest_mjpeg_generator(hud=hud))
        return jsonify(ok=False, error="stream_unavailable", reason="status_error"), 503

    # אם יש גנרטור JPEG מה-Streamer — השתמש בו
    gen = getattr(s, "get_jpeg_generator", None)
    if not callable(gen):
        # אין גנרטור? נסה ingest
        if INGEST.jpeg is not None:
            logger.warning("stream.mjpg: streamer has no generator — fallback to INGEST")
            return _make_mjpeg_response(_ingest_mjpeg_generator(hud=hud))
        return jsonify(ok=False, error="jpeg_generator_not_available"), 503

    try:
        base_gen = gen()
        if hud:
            # נעטוף כדי לצייר HUD על כל פריים מה-Streamer
            def _wrap_with_hud() -> Iterator[bytes]:
                for frame in base_gen:
                    # frame צפוי להיות bytes של JPEG
                    try:
                        extra = {
                            "ingest_fps": f"{INGEST.rx_fps.fps():.1f}",
                            "encode_fps": f"{INGEST.enc_fps.fps():.1f}",
                            "size": f"{s.width}x{s.height}" if hasattr(s, "width") and hasattr(s, "height") else "–",
                            "lat_ms": None,
                            "source": s.source_desc(),
                            "state": "STREAMER",
                            "jpeg_quality": getattr(s, "jpeg_quality", 80),
                        }
                        frame = _overlay_hud(frame, label="BodyPlus_XPro", extra=extra)
                    except Exception:
                        pass
                    yield (
                        _BOUNDARY + b"\r\n"
                        + b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                        + frame + b"\r\n"
                    )
            logger.info("stream.mjpg: using STREAMER with HUD")
            return _make_mjpeg_response(_wrap_with_hud())
        else:
            logger.info("stream.mjpg: using STREAMER without HUD")
            # אם ה-Streamer כבר מחזיר גושי multipart — אל תעטוף פעמיים:
            # נניח שהוא מחזיר JPEG נקי (bytes) — לכן נעטוף במולטיפארט מינימלי.
            def _wrap_plain() -> Iterator[bytes]:
                for frame in base_gen:
                    yield (
                        _BOUNDARY + b"\r\n"
                        + b"Content-Type: image/jpeg\r\n"
                        + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                        + frame + b"\r\n"
                    )
            return _make_mjpeg_response(_wrap_plain())
    except Exception as e:
        logger.error("[video_stream_mjpg] STREAMER error", exc_info=True)
        # נסה ingest בפאלבק אחרון
        if INGEST.jpeg is not None:
            logger.warning("stream.mjpg: error — fallback to INGEST")
            return _make_mjpeg_response(_ingest_mjpeg_generator(hud=hud))
        return jsonify(ok=False, error=str(e)), 500

def _make_mjpeg_response(gen: Iterator[bytes]) -> Response:
    boundary = "frame"
    resp = Response(stream_with_context(gen),
                    mimetype=f"multipart/x-mixed-replace; boundary={boundary}")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

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
            if ok:
                return jsonify(ok=True, message=msg,
                               settings={"fps": int(s.fps), "width": int(s.width), "height": int(s.height)}), 200
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
        try: s.stop_auto_capture()
        except Exception: pass
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

    try:
        apply_fn = getattr(s, "apply_camera_settings", None)
        if callable(apply_fn):
            ok, msg = apply_fn(width=width, height=height)
            if ok:
                return jsonify(ok=True, message=msg, width=int(s.width), height=int(s.height)), 200
    except Exception:
        pass

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

# ---------- Extras ----------
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
