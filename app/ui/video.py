# -*- coding: utf-8 -*-
"""
app/ui/video.py — VideoStreamer ingest-only (ללא OpenCV)
---------------------------------------------------------
🎥 תיאור:
- מקבל פריימים JPEG (טלפון / דפדפן) ומזרימם לשרת כ-MJPEG.
- ללא שימוש ב-OpenCV.
- משמש מקור עיקרי ל-/video/stream.mjpg ולמדידות Live.

⚙️ נקודות עיקריות:
- ingest_jpeg(jpeg_bytes): קבלת פריים מהדפדפן.
- get_jpeg_generator(): הפקת סטרים MJPEG.
- get_latest_jpeg(): החזרת הפריים האחרון למדידות.
- has_frames() / buffer_len(): תאימות מלאה לנתיב /video/stream.mjpg.
- ✅ read_frame(self): מתודה שמחזירה numpy RGB (ללא OpenCV) — תואם ל-main.py שקורא s.read_frame().
"""

from __future__ import annotations
import os
import time
import threading
import logging
from typing import Optional, Tuple, List, Dict, Any
from io import BytesIO

# ===== Logger =====
logger = logging.getLogger("VideoStreamer")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ===== PIL + numpy (ללא OpenCV) =====
try:
    from PIL import Image  # type: ignore
    import numpy as np     # type: ignore
    PIL_OK = True
except Exception as e:
    Image = None  # type: ignore
    np = None     # type: ignore
    PIL_OK = False
    logger.warning(f"PIL/numpy unavailable — {e!r}")

def _safe_now() -> float:
    try:
        return time.time()
    except Exception:
        return float(int(time.time()))

# ===== Placeholder image (אם אין פריימים) =====
_MINI_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08" * 64 +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
)

class VideoStreamer:
    """מקבל JPEG מבחוץ ומספק סטרים MJPEG לזיכרון — ללא OpenCV."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        jpeg_quality: int = 70,
        show_preview_default: bool = False,
        window_name: str = "Preview",
    ):
        self.camera_index = int(camera_index)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.jpeg_quality = int(jpeg_quality)
        self.window_name = window_name

        self.encode_fps: int = int(os.getenv("MJPEG_FPS", str(min(self.fps, 15))))
        self._next_encode_due: float = 0.0

        self._opened = False
        self._running = False
        self._last_jpeg: Optional[bytes] = None
        self._last_size: Optional[Tuple[int, int]] = None
        self._last_push_ts: float = 0.0

        self._fps_win: List[float] = []
        self._last_fps: Optional[float] = None

        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        self._source_desc: Optional[str] = "ingest-only"
        self._frozen = False
        self._freeze_until: Optional[float] = None

        self.on_open_metrics = None
        self.on_freeze_change = None

        logger.info(f"VideoStreamer initialized | {width}x{height} @ {fps}fps | ingest-only mode")

    # -------- Status --------
    def is_open(self) -> bool:
        return bool(self._opened)

    def is_running(self) -> bool:
        return bool(self._running)

    def last_fps(self) -> Optional[float]:
        return float(self._last_fps) if self._last_fps is not None else None

    def last_frame_size(self) -> Optional[Tuple[int, int]]:
        return tuple(self._last_size) if self._last_size else None

    def get_light_mode(self) -> str:
        return "normal"

    def source_desc(self) -> Optional[str]:
        return self._source_desc

    # -------- תאימות ל־routes_video --------
    def has_frames(self) -> bool:
        """בודק אם קיים פריים אחרון בזיכרון."""
        return self._last_jpeg is not None

    def buffer_len(self) -> int:
        """תאימות לגרסה ישנה – מחזיר 1 אם קיים פריים."""
        return 1 if self._last_jpeg is not None else 0

    # -------- Camera settings (headless) --------
    def get_camera_settings(self) -> Dict[str, int]:
        return {"width": int(self.width), "height": int(self.height), "fps": int(self.fps)}

    def set_resolution(self, width: int, height: int) -> None:
        try:
            self.width, self.height = int(width), int(height)
            self._last_size = (self.width, self.height)
        except Exception:
            pass

    def apply_camera_settings(
        self,
        *,
        fps: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ):
        if fps is not None:
            try:
                self.fps = int(fps)
            except Exception:
                pass
        if width is not None:
            try:
                self.width = int(width)
            except Exception:
                pass
        if height is not None:
            try:
                self.height = int(height)
            except Exception:
                pass
        self._last_size = (int(self.width), int(self.height))
        return True, "applied_headless"

    # -------- Ingest bridge --------
    def ingest_jpeg(self, jpeg_bytes: bytes) -> None:
        if not isinstance(jpeg_bytes, (bytes, bytearray)) or len(jpeg_bytes) < 10:
            return
        now = _safe_now()
        self._opened = True
        self._running = True
        self._last_push_ts = now

        if PIL_OK:
            try:
                with Image.open(BytesIO(jpeg_bytes)) as im:  # type: ignore
                    self._last_size = (int(im.width), int(im.height))
            except Exception:
                pass

        if self.encode_fps > 0 and now < self._next_encode_due:
            return
        self._next_encode_due = now + (1.0 / float(self.encode_fps)) if self.encode_fps > 0 else now

        with self._cv:
            self._last_jpeg = bytes(jpeg_bytes)
            self._cv.notify_all()

        self._update_fps(now)
        logger.debug("Frame ingested | size=%d bytes | fps≈%s", len(jpeg_bytes), self._last_fps or 0)

    # -------- MJPEG generator --------
    def get_jpeg_generator(self):
        boundary = b"--frame"
        heartbeat = _safe_now() + 2.0
        while True:
            with self._cv:
                if self._last_jpeg is None:
                    self._cv.wait(timeout=0.5)
                data = self._last_jpeg
            if data is None:
                if _safe_now() > heartbeat:
                    self._ensure_placeholder_jpeg()
                    heartbeat = _safe_now() + 2.0
                time.sleep(0.05)
                continue
            yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"

    iter_mjpeg = get_jpeg_generator  # alias

    # -------- Accessor for metrics worker --------
    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return bytes(self._last_jpeg) if self._last_jpeg is not None else None

    # -------- Freeze/preview (no-op) --------
    def enable_preview(self, on: bool):
        return

    def start_auto_capture(self):
        self._source_desc = "ingest-only"
        self._ensure_placeholder_jpeg()
        logger.info("Auto-capture simulated (placeholder ready)")

    def stop_auto_capture(self):
        self._running = False
        self._opened = False
        logger.info("Video capture stopped (logical)")

    # -------- ✅ read_frame כמתודה (ללא OpenCV) --------
    def read_frame(self) -> Tuple[bool, Optional[Any]]:
        """
        מחזיר פריים כ-numpy array בפורמט RGB (ללא cv2).
        תואם ל-main.py שקורא s.read_frame().
        """
        if not PIL_OK or np is None:
            return False, None
        jpeg = self.get_latest_jpeg()
        if not jpeg:
            return False, None
        try:
            with Image.open(BytesIO(jpeg)) as im:  # type: ignore
                arr = np.array(im.convert("RGB"))  # type: ignore
                return True, arr
        except Exception as e:
            logger.debug("read_frame() decode error: %r", e)
            return False, None

    # -------- Internals --------
    def _ensure_placeholder_jpeg(self):
        if self._last_jpeg is None:
            self._last_jpeg = _MINI_JPEG

    def _update_fps(self, now: float):
        self._fps_win.append(now)
        while self._fps_win and (now - self._fps_win[0] > 1.0):
            self._fps_win.pop(0)
        if len(self._fps_win) >= 2:
            span = self._fps_win[-1] - self._fps_win[0]
            if span > 0:
                self._last_fps = round((len(self._fps_win) - 1) / span, 2)

# ===== Singleton streamer =====
_streamer: Optional[VideoStreamer] = None

def get_streamer() -> VideoStreamer:
    """יוצר אובייקט גלובלי יחיד של VideoStreamer."""
    global _streamer
    if _streamer is None:
        cam = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))
        w = int(os.getenv("WIDTH", "1280"))
        h = int(os.getenv("HEIGHT", "720"))
        fps = int(os.getenv("FPS", "30"))
        q = int(os.getenv("JPEG_QUALITY", "70"))  # נשמר לתאימות, לא בשימוש כאן
        _streamer = VideoStreamer(cam, w, h, fps, q, False)
        logger.info("get_streamer(): new instance created (%dx%d@%d)", w, h, fps)
    return _streamer

# ===== פונקציה גלובלית אופציונלית (למי שקורא read_frame() בלי האובייקט) =====
def read_frame() -> Tuple[bool, Optional[Any]]:
    s = get_streamer()
    return s.read_frame()
