# -*- coding: utf-8 -*-
# =============================================================================
# routes_video.py — וידאו: ingest ← דפדפן/טלפון → סטרים MJPEG עם HUD
# -----------------------------------------------------------------------------
# מטרת הקובץ (בקצרה):
# • לקלוט פריימים ב-/api/ingest_frame (raw image/jpeg או multipart 'frame')
# • להזרים /video/stream.mjpg (עם HUD) — ממקור מצלמה (streamer) או ingest (fallback)
# • לחשוף /api/video/start|stop|status + /api/camera/settings + /api/video/params|resolution
#
# חיבור לפייפליין:
# • בכל POST /api/ingest_frame אנחנו גם קוראים ל-s.ingest_jpeg(jpeg) (אם קיים) —
#   כדי שהפייפליין (MediaPipe/OD/מדידות) ירוץ על הפריימים מהדפדפן, ו-/payload יתעדכן.
#
# תלות: get_streamer() מתוך app.ui.video (יש בו ingest_jpeg, push_bgr_frame, push_jpeg).
# HUD: מצוייר עם Pillow אם זמין; אם לא — הסטרים עובד בלי HUD.
# =============================================================================

from __future__ import annotations
import os, time, logging, base64
from typing import Callable, Tuple, Dict, Any, Optional, Deque, Iterator
from collections import deque
from io import BytesIO

from flask import Blueprint, Response, jsonify, request, redirect, stream_with_context

# ---------- Logger ----------
logger = logging.getLogger("routes_video")
if not logger.handlers:
    _h = logging.StreamHandler()
    _fmt = logging.Formatter("[%(asctime)s] %(levelname)s routes_video: %(message)s")
    _h.setFormatter(_fmt)
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ---------- Video streamer (אם זמין) ----------
try:
    from app.ui.video import get_streamer  # כולל ingest_jpeg(), push_jpeg(), get_jpeg_generator()
    _HAS_STREAMER = True
except Exception:
    _HAS_STREAMER = False
    def get_streamer():
        raise RuntimeError("get_streamer() unavailable")

# מצב מקור 'file' (אם מודול העלאת וידאו קיים)
try:
    from admin_web.routes_upload_video import get_stream_mode  # type: ignore
except Exception:
    def get_stream_mode() -> str:
        return "camera"

video_bp = Blueprint("video", __name__)

DEFAULT_CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))
_BOUNDARY = b"--frame"

def _now_ms() -> int:
    return int(time.time() * 1000)

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

def _clip_int(val, lo, hi, default):
    try:
        v = int(val)
    except Exception:
        return int(default)
    return int(max(lo, min(hi, v)))

# ---------- HUD (Pillow אם זמין) ----------
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False
    Image = ImageDraw = ImageFont = None  # type: ignore

def _load_font(size: int = 18):
    if not _HAS_PIL:
        return None
    try:
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
    if not _HAS_PIL:
        return jpeg_bytes
    try:
        im = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
    except Exception:
        return jpeg_bytes

    draw = ImageDraw.Draw(im)
    font = _HUD_FONT

    lines = [f"{label}", f"time: {time.strftime('%H:%M:%S')}"]
    for k in ("ingest_fps", "encode_fps", "size", "lat_ms", "source", "state"):
        if k in extra:
            lines.append(f"{k}: {extra[k]}")

    pad = 8
    line_h = 22 if font else 18
    try:
        w_calc = [draw.textlength(l, font=font) for l in lines]
    except Exception:
        w_calc = [len(l)*9 for l in lines]
    box_w = int(10 + max(w_calc) + 2*pad)
    box_h = int(10 + line_h*len(lines) + 2*pad)
    x0, y0 = 10, 10
    x1, y1 = x0 + box_w, y0 + box_h

    draw.rectangle((x0, y0, x1, y1), fill=(0, 0, 0))
    y = y0 + pad
    for i, l in enumerate(lines):
        color = (180, 220, 255) if i == 0 else (255, 255, 255)
        draw.text((x0 + pad, y), l, fill=color, font=font)
        y += line_h

    out = BytesIO()
    im.save(out, format="JPEG", quality=int(extra.get("jpeg_quality", 80)))
    return out.getvalue()

# ---------- FPS meters ----------
class _FPSMeter:
    def __init__(self, window_sec: float = 2.0):
        self.window = window_sec
        self.ts: Deque[float] = deque(maxlen=200)
    def tick(self) -> None:
        t = time.time()
        self.ts.append(t)
        while self.ts and (t - self.ts[0] > self.window):
            self.ts.popleft()
    def fps(self) -> float:
        if len(self.ts) < 2:
            return 0.0
        dt = max(1e-6, self.ts[-1] - self.ts[0])
        return (len(self.ts) - 1) / dt

# ---------- ingest state ----------
class _IngestState:
    def __init__(self):
        self.jpeg: Optional[bytes] = None
        self.ts_ms: int = 0
        self.size: Optional[tuple[int,int]] = None
        self.rx_fps = _FPSMeter(2.0)
        self.enc_fps = _FPSMeter(2.0)

INGEST = _IngestState()

# JPEG placeholder קטן (תקין מבחינת padding)
_PLACEHOLDER_B64 = (
    b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxISEhUTEhMVFRUVFRUVFRUVFRUVFRUWFxUVFRUY"
    b"HSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGi0fHyUtLS0tLS0tLS0tLS0t"
    b"LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAJYA2gMBIgACEQEDEQH/xAAX"
    b"AQEBAQEAAAAAAAAAAAAAAAAAAgMF/8QAHxAAAgICAwEAAAAAAAAAAAAAAQIAAxESITEEUXGB/8QA"
    b"FQEBAQAAAAAAAAAAAAAAAAAABQb/xAAZEQADAAMAAAAAAAAAAAAAAAAAARECEhP/2gAMAwEAAhED"
    b"EQAAAPcAAAAAAABnq0sZlq0sZlq0sZlq0sZlq0sZlq0sZlq0sZlq0sYAAAAAAAAB3w7DqPp9f7cY"
    b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//Z"
)
_PLACEHOLDER_JPEG = base64.b64decode(_PLACEHOLDER_B64 + b'=' * (-len(_PLACEHOLDER_B64) % 4))

def _read_jpeg_from_request() -> Tuple[Optional[bytes], Optional[str]]:
    ct = (request.headers.get("Content-Type") or "").lower()
    if "multipart/form-data" in ct:
        f = request.files.get("frame")
        if not f:
            return None, "missing 'frame' file field"
        return f.read(), None
    if "image/jpeg" in ct or "image/jpg" in ct:
        data = request.get_data()
        if not data:
            return None, "empty body"
        return data, None
    return None, f"unsupported Content-Type: {ct or 'N/A'}"

@video_bp.post("/api/ingest_frame")
def api_ingest_frame():
    """
    קולט פריים בודד כ-JPEG (raw או multipart). בנוסף:
    • מעדכן INGEST להצגה (fallback)
    • מזריק ל-Streamer (ingest_jpeg) כדי שהפייפליין ירוץ ו-/payload יתעדכן
    """
    try:
        jpeg, err = _read_jpeg_from_request()
        if err or not jpeg:
            return jsonify(ok=False, error=err or "bad frame"), 400

        # עדכון גודל (סטטוס) — best-effort
        try:
            if _HAS_PIL:
                im = Image.open(BytesIO(jpeg))
                INGEST.size = im.size  # type: ignore[attr-defined]
        except Exception:
            pass

        # שמירה ל-fallback MJPEG + מדדי ingest
        INGEST.jpeg = jpeg
        INGEST.ts_ms = _now_ms()
        INGEST.rx_fps.tick()

        # >>> החיבור לפייפליין: להזרים ל-Streamer <<<
        try:
            if _HAS_STREAMER:
                s = get_streamer()
                ing = getattr(s, "ingest_jpeg", None)
                if callable(ing):
                    ing(jpeg)   # מפענח → push_bgr_frame → payload/OD רצים
                else:
                    # לפחות נציג במפלג ה-MJPEG:
                    push = getattr(s, "push_jpeg", None)
                    if callable(push):
                        push(jpeg, size=INGEST.size)
        except Exception:
            logger.exception("ingest → streamer failed")

        return jsonify(ok=True, ts_ms=INGEST.ts_ms)
    except Exception as e:
        logger.error("api_ingest_frame failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

def _ingest_mjpeg_generator(hud: bool = True, fps: int = 12) -> Iterator[bytes]:
    """שומר קצב קבוע; אם אין ingest — שולח placeholder כדי שהדפדפן לא ייחנק."""
    interval = 1.0 / max(1, min(60, fps))
    while True:
        t0 = time.time()
        frame = INGEST.jpeg if INGEST.jpeg is not None else _PLACEHOLDER_JPEG
        extra = {
            "ingest_fps": f"{INGEST.rx_fps.fps():.1f}",
            "encode_fps": f"{INGEST.enc_fps.fps():.1f}",
            "size": f"{INGEST.size[0]}x{INGEST.size[1]}" if INGEST.size else "–",
            "lat_ms": (_now_ms() - INGEST.ts_ms) if INGEST.ts_ms else None,
            "source": "capture" if INGEST.jpeg is not None else "placeholder",
            "state": "INGEST" if INGEST.jpeg is not None else "IDLE",
            "jpeg_quality": 80,
        }
        out = _overlay_hud(frame, label="BodyPlus_XPro", extra=extra) if hud else frame

        INGEST.enc_fps.tick()
        yield (
            _BOUNDARY + b"\r\n"
            + b"Content-Type: image/jpeg\r\n"
            + f"Content-Length: {len(out)}\r\n\r\n".encode("ascii")
            + out + b"\r\n"
        )

        elapsed = time.time() - t0
        time.sleep(max(0.0, interval - elapsed))

# ---------- START / STOP / STATUS ----------
@video_bp.post("/api/video/start")
def api_video_start():
    j = request.get_json(silent=True) or {}
    cam_idx = j.get("camera_index", DEFAULT_CAMERA_INDEX)
    show_preview = bool(j.get("show_preview", False))
    if not _HAS_STREAMER:
        return jsonify(ok=False, error="streamer_unavailable"), 501
    s = get_streamer()
    logger.info(f"/api/video/start (camera_index={cam_idx}, preview={show_preview})")

    try:
        if s.is_running():
            s.stop_auto_capture()
            _wait_until(lambda: not bool(s.is_running()), 2.0, 0.05)
        if s.is_open():
            _try_close_all(s); time.sleep(0.2)
    except Exception:
        pass

    try:
        s.camera_index = int(cam_idx)
    except Exception:
        pass

    try:
        s.start_auto_capture()
        try: s.enable_preview(show_preview)
        except Exception: pass
        return jsonify(ok=True, source=s.source_desc()), 200
    except Exception as e:
        logger.error("/api/video/start failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.post("/api/video/stop")
def api_video_stop():
    if not _HAS_STREAMER:
        return jsonify(ok=True)
    s = get_streamer()
    try:
        try: s.stop_auto_capture()
        except Exception: pass
        _wait_until(lambda: not bool(s.is_running()), 2.0, 0.05)
        try:
            if s.is_open():
                _try_close_all(s)
        except Exception:
            pass
        try: s.enable_preview(False)
        except Exception: pass
        return jsonify(ok=True), 200
    except Exception as e:
        logger.error("/api/video/stop failed", exc_info=True)
        return jsonify(ok=False, error=str(e)), 500

@video_bp.get("/api/video/status")
def api_video_status():
    opened = running = False
    size = fps = source = light_mode = None
    preview_window_open = False
    state = "ACTIVE"

    if _HAS_STREAMER:
        try:
            s = get_streamer()
            opened = bool(s.is_open())
            running = bool(s.is_running()) and opened
            size = s.last_frame_size()
            fps = s.last_fps()
            source = s.source_desc()
            try: light_mode = s.get_light_mode()
            except Exception: light_mode = None
            try: preview_window_open = bool(getattr(s, "_preview", False))
            except Exception: preview_window_open = False
            try:
                if bool(getattr(s, "_frozen", False)) or getattr(s, "_freeze_until", None):
                    state = "FROZEN"
            except Exception:
                pass
        except Exception:
            pass

    ingest_state = {
        "has_frame": INGEST.jpeg is not None,
        "rx_fps": round(INGEST.rx_fps.fps(), 1),
        "enc_fps": round(INGEST.enc_fps.fps(), 1),
        "last_ts_ms": INGEST.ts_ms,
        "lat_ms": (_now_ms() - INGEST.ts_ms) if INGEST.ts_ms else None,
        "size": list(INGEST.size) if INGEST.size else None,
    }
    return jsonify(
        ok=True, error=None,
        opened=opened, running=running, fps=fps, size=size,
        source=source, light_mode=light_mode, preview_window_open=preview_window_open,
        state=state, ingest=ingest_state
    ), 200

# ---------- STREAM ----------
@video_bp.get("/video/stream.mjpg")
def video_stream_mjpg():
    hud = request.args.get("hud", "1").strip() != "0"

    try:
        if get_stream_mode() == "file":
            return redirect("/video/stream_file.mjpg", code=307)
    except Exception:
        pass

    if _HAS_STREAMER:
        try:
            s = get_streamer()
            if s.is_open() and s.is_running():
                gen = getattr(s, "get_jpeg_generator", None)
                if callable(gen):
                    base_gen = gen()

                    if hud and _HAS_PIL:
                        def _wrap_with_hud() -> Iterator[bytes]:
                            for frame in base_gen:
                                try:
                                    extra = {
                                        "ingest_fps": f"{INGEST.rx_fps.fps():.1f}",
                                        "encode_fps": f"{INGEST.enc_fps.fps():.1f}",
                                        "size": f"{getattr(s, 'width', 0)}x{getattr(s, 'height', 0)}",
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
                        return _make_mjpeg_response(_wrap_with_hud())
                    else:
                        def _wrap_plain() -> Iterator[bytes]:
                            for frame in base_gen:
                                yield (
                                    _BOUNDARY + b"\r\n"
                                    + b"Content-Type: image/jpeg\r\n"
                                    + f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                                    + frame + b"\r\n"
                                )
                        return _make_mjpeg_response(_wrap_plain())
        except Exception:
            logger.warning("streamer not available; falling back to ingest")

    return _make_mjpeg_response(_ingest_mjpeg_generator(hud=hud))

@video_bp.get("/video/stream")
def video_stream_legacy():
    return redirect("/video/stream.mjpg", code=302)

# ---------- PARAMS / RESOLUTION ----------
@video_bp.route("/api/video/params", methods=["GET", "POST"])
def api_video_params():
    if request.method == "GET":
        if not _HAS_STREAMER:
            return jsonify(ok=True, params={"jpeg_quality": 70, "encode_fps": 12, "target_fps": 20, "decimation": 1}), 200
        s = get_streamer()
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
    if not _HAS_STREAMER:
        return jsonify(ok=False, error="streamer_unavailable"), 501
    s = get_streamer()
    profile = (j.get("profile") or "").strip().lower()

    profiles = {
        "eco":      {"jpeg_quality": 55, "encode_fps": 8,  "target_fps": 10, "decimation": 2},
        "balanced": {"jpeg_quality": 70, "encode_fps": 12, "target_fps": 20, "decimation": 1},
        "quality":  {"jpeg_quality": 85, "encode_fps": 15, "target_fps": 30, "decimation": 1},
    }
    try:
        if profile in profiles:
            p = profiles[profile]
            s.jpeg_quality = int(p["jpeg_quality"])
            s.encode_fps   = int(p["encode_fps"])
            s.target_fps   = int(p["target_fps"])
            if hasattr(s, "set_decimation"): s.set_decimation(int(p["decimation"]))
            return jsonify(ok=True, applied="profile", profile=profile, params=p), 200

        if "jpeg_quality" in j: s.jpeg_quality = _clip_int(j["jpeg_quality"], 40, 95, getattr(s, "jpeg_quality", 70))
        if "encode_fps"   in j: s.encode_fps   = _clip_int(j["encode_fps"],   0, 60, getattr(s, "encode_fps", 15))
        if "target_fps"   in j: s.target_fps   = _clip_int(j["target_fps"],   0, 60, getattr(s, "target_fps", getattr(s, "fps", 30)))
        if "decimation"   in j and hasattr(s, "set_decimation"):
            s.set_decimation(_clip_int(j["decimation"], 1, 8, 1))
        out = {
            "jpeg_quality": int(getattr(s, "jpeg_quality", 70)),
            "encode_fps":   int(getattr(s, "encode_fps", 15)),
            "target_fps":   int(getattr(s, "target_fps", getattr(s, "fps", 30))),
            "decimation":   int(getattr(s, "_decimation", 1)),
        }
        return jsonify(ok=True, applied="manual", params=out), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@video_bp.post("/api/video/resolution")
def api_video_resolution():
    if not _HAS_STREAMER:
        return jsonify(ok=False, error="streamer_unavailable"), 501
    s = get_streamer()
    j = request.get_json(silent=True) or {}
    preset = (j.get("preset") or "").strip().lower()

    if preset:
        if preset == "low":    width, height = 640, 360
        elif preset == "medium": width, height = 1280, 720
        elif preset == "high": width, height = 1920, 1080
        else: return jsonify(ok=False, error="unknown_preset"), 400
    else:
        try:
            width, height = int(j.get("width")), int(j.get("height"))
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
        _wait_until(lambda: not bool(s.is_running()), 2.0, 0.05)
        try: s.width = int(width)
        except Exception: pass
        try: s.height = int(height)
        except Exception: pass
        if s.is_open(): _try_close_all(s); time.sleep(0.2)
        s.start_auto_capture()
        return jsonify(ok=True, message="restarted_with_new_resolution",
                       width=int(s.width), height=int(s.height)), 200
    except Exception as e:
        logger.error("/api/video/resolution failed", exc_info=True)
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
