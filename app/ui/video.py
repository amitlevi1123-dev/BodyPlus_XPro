# -*- coding: utf-8 -*-
"""
app/ui/video.py — VideoStreamer ingest-only (ללא OpenCV)
- ingest_jpeg(jpeg_bytes) מהדפדפן/טלפון
- get_jpeg_generator() למתן MJPEG
- get_latest_jpeg() לחשיפת הפריים האחרון למדידות
"""

from __future__ import annotations
import os, time, threading
from typing import Optional, Tuple, List, Dict, Any
from io import BytesIO

try:
    from PIL import Image  # type: ignore
    PIL_OK = True
except Exception:
    Image = None  # type: ignore
    PIL_OK = False

def _safe_now() -> float:
    try: return time.time()
    except Exception: return float(int(time.time()))

_MINI_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08"*64 +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
)

class VideoStreamer:
    def __init__(self, camera_index: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 30, jpeg_quality: int = 70, show_preview_default: bool = False,
                 window_name: str = "Preview"):
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

    # -------- Status --------
    def is_open(self) -> bool:       return bool(self._opened)
    def is_running(self) -> bool:    return bool(self._running)
    def last_fps(self) -> Optional[float]:       return float(self._last_fps) if self._last_fps is not None else None
    def last_frame_size(self) -> Optional[Tuple[int,int]]: return tuple(self._last_size) if self._last_size else None
    def get_light_mode(self) -> str: return "normal"
    def source_desc(self) -> Optional[str]:      return self._source_desc

    # -------- Camera settings (headless) --------
    def get_camera_settings(self) -> Dict[str,int]:
        return {"width": int(self.width), "height": int(self.height), "fps": int(self.fps)}

    def set_resolution(self, width: int, height: int) -> None:
        try:
            self.width, self.height = int(width), int(height)
            self._last_size = (self.width, self.height)
        except Exception:
            pass

    def apply_camera_settings(self, *, fps: Optional[int] = None, width: Optional[int] = None,
                              height: Optional[int] = None):
        if fps   is not None:
            try: self.fps = int(fps)
            except Exception: pass
        if width is not None:
            try: self.width = int(width)
            except Exception: pass
        if height is not None:
            try: self.height = int(height)
            except Exception: pass
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

    # -------- Optional manual push --------
    def push_jpeg(self, jpeg_bytes: bytes, size: Optional[Tuple[int,int]] = None) -> None:
        if not isinstance(jpeg_bytes, (bytes, bytearray)) or len(jpeg_bytes) < 10:
            return
        now = _safe_now()
        if self.encode_fps > 0 and now < self._next_encode_due:
            return
        self._next_encode_due = now + (1.0 / float(self.encode_fps)) if self.encode_fps > 0 else now
        self._opened = True
        self._running = True
        self._last_push_ts = now
        if size:
            try: self._last_size = (int(size[0]), int(size[1]))
            except Exception: pass
        with self._cv:
            self._last_jpeg = bytes(jpeg_bytes)
            self._cv.notify_all()
        self._update_fps(now)

    # -------- MJPEG --------
    def get_jpeg_generator(self):
        boundary = b"--frame"; heartbeat = _safe_now() + 2.0
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

    iter_mjpeg = get_jpeg_generator

    # -------- Accessor for metrics worker --------
    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return bytes(self._last_jpeg) if self._last_jpeg is not None else None

    # -------- Freeze/preview (no-op) --------
    def enable_preview(self, on: bool): return
    def start_auto_capture(self): self._source_desc = "ingest-only"; self._ensure_placeholder_jpeg()
    def stop_auto_capture(self): self._running = False; self._opened = False

    # -------- Internals --------
    def _ensure_placeholder_jpeg(self):
        if self._last_jpeg is None: self._last_jpeg = _MINI_JPEG

    def _update_fps(self, now: float):
        self._fps_win.append(now)
        while self._fps_win and (now - self._fps_win[0] > 1.0):
            self._fps_win.pop(0)
        if len(self._fps_win) >= 2:
            span = self._fps_win[-1] - self._fps_win[0]
            if span > 0: self._last_fps = round((len(self._fps_win) - 1) / span, 2)

_streamer: Optional[VideoStreamer] = None

def get_streamer() -> VideoStreamer:
    global _streamer
    if _streamer is None:
        cam = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))
        w = int(os.getenv("WIDTH", "1280")); h = int(os.getenv("HEIGHT", "720"))
        fps = int(os.getenv("FPS", "30")); q = int(os.getenv("JPEG_QUALITY", "70"))
        _streamer = VideoStreamer(cam, w, h, fps, q, False)
    return _streamer
