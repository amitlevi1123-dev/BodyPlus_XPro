# -*- coding: utf-8 -*-
"""
app/ui/video.py
--------------------------------------------
🎥 VideoStreamer — סטרימר MJPEG ללא OpenCV (ingest-only):
- ingest_jpeg(jpeg_bytes): קולט פריימים (JPEG) מהדפדפן/טלפון.
- push_jpeg: שומר את ה-JPEG האחרון ומודיע לגנרטור.
- get_jpeg_generator(): מייצר סטרים MJPEG רציף מן הזיכרון.

⚠️ בטוח לענן:
- לא פותח מצלמה בכלל (אין שימוש ב-OpenCV).
- תצוגת Preview היא no-op.
- הגדרות מצלמה/רזולוציה חוזרות "applied_headless".

שילוב:
- admin_web.routes_video קורא get_streamer() ומשתמש ב-get_jpeg_generator()
  כדי להגיש /video/stream.mjpg. הדפדפן מזרים פריימים אל /api/ingest_frame.
"""

from __future__ import annotations
import os
import time
import threading
from typing import Optional, Tuple, List, Dict, Any
from io import BytesIO

# PIL אופציונלי (רק אם תרצה לפענח JPEG כדי לדעת גודל)
try:
    from PIL import Image  # type: ignore
    PIL_OK = True
except Exception:
    Image = None  # type: ignore
    PIL_OK = False


# ============================== Utilities ==============================

def _safe_now() -> float:
    try:
        return time.time()
    except Exception:
        return float(int(time.time()))


# JPEG מינימלי (1x1) — לשימוש כ-placeholder אם אין שום פריים עדיין
_MINI_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08"*64 +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
)


# ============================== VideoStreamer ==============================

class VideoStreamer:
    """
    סטרימר MJPEG פשוט מבוסס ingest בלבד (ללא OpenCV).
    שומר את הפריים האחרון (JPEG) ומזרים אותו כ-MJPEG.
    """

    def __init__(
        self,
        camera_index: int = 0,   # ללא שימוש בפועל — נשמר לתאימות API
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        jpeg_quality: int = 70,  # ללא שימוש כאן (אנקודינג נעשה בצד השולח)
        show_preview_default: bool = False,
        window_name: str = "Preview"  # ללא שימוש
    ):
        # פרמטרים לוגיים (לשקיפות API)
        self.camera_index = int(camera_index)
        self.width = int(width)
        self.height = int(height)
        self.fps = int(fps)
        self.jpeg_quality = int(jpeg_quality)
        self.window_name = window_name

        # ריסטריקציה על קצב דחיפת פריימים ל-MJPEG (כמה פעמים נרצה "לשחרר" פריים ללקוח)
        self.encode_fps: int = int(os.getenv("MJPEG_FPS", str(min(self.fps, 15))))
        self._next_encode_due: float = 0.0

        # סטייט
        self._opened = False
        self._running = False
        self._last_jpeg: Optional[bytes] = None
        self._last_size: Optional[Tuple[int, int]] = None  # (w,h) אם ידוע
        self._last_push_ts: float = 0.0

        # FPS חישוב גס
        self._fps_win: List[float] = []
        self._last_fps: Optional[float] = None

        # מנעולים/תזמון
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        # "מצבים" נוספים לשמירה על תאימות API
        self._source_desc: Optional[str] = "ingest-only"
        self._frozen = False
        self._freeze_until: Optional[float] = None

        # Hooks (לא חובה להשתמש)
        self.on_open_metrics: Optional[callable] = None
        self.on_freeze_change: Optional[callable] = None

        # אין פתיחת מצלמה אוטומטית — זה קובץ ללא OpenCV

    # ------------ Status ------------
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

    # ------------ Camera settings helpers (no-op/headless) ------------
    def get_camera_settings(self) -> Dict[str, int]:
        # מחזיר את מה שהוגדר ידנית — אין מצלמה אמיתית בצד השרת
        return {"width": int(self.width), "height": int(self.height), "fps": int(self.fps)}

    def set_resolution(self, width: int, height: int) -> None:
        # מעדכן ערכי יעד להצגה/דיאגנוסטיקה (לא פותח מצלמה)
        try:
            w, h = int(width), int(height)
            self.width, self.height = w, h
            self._last_size = (w, h)
        except Exception:
            pass

    def apply_camera_settings(
        self, *, fps: Optional[int] = None, width: Optional[int] = None, height: Optional[int] = None
    ) -> Tuple[bool, str]:
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

        # אין מצלמה לפתוח/לכוון — אנחנו headless
        self._last_size = (int(self.width), int(self.height))
        return True, "applied_headless"

    # ------------ Public ingest bridge ------------
    def ingest_jpeg(self, jpeg_bytes: bytes) -> None:
        """
        קולט JPEG מהלקוח ושומר לפריים האחרון. אם אפשר — דוגם גודל.
        """
        if not isinstance(jpeg_bytes, (bytes, bytearray)) or len(jpeg_bytes) < 10:
            return

        # עדכון סטייט ריצה
        now = _safe_now()
        self._opened = True
        self._running = True
        self._last_push_ts = now

        # ניסיון לשער גודל (לא חובה)
        if PIL_OK:
            try:
                with Image.open(BytesIO(jpeg_bytes)) as im:  # type: ignore
                    self._last_size = (int(im.width), int(im.height))
            except Exception:
                pass

        # קצב פלט MJPEG מרוסן ע"י encode_fps (לא לעדכן מהר מדי את הלקוח)
        if self.encode_fps > 0 and now < self._next_encode_due:
            return
        self._next_encode_due = now + (1.0 / float(self.encode_fps)) if self.encode_fps > 0 else now

        with self._cv:
            self._last_jpeg = bytes(jpeg_bytes)
            self._cv.notify_all()

        self._update_fps(now)

    # ------------ Push APIs (למקרה שתרצה לדחוף JPEG ידנית) ------------
    def push_jpeg(self, jpeg_bytes: bytes, size: Optional[Tuple[int, int]] = None) -> None:
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
            try:
                self._last_size = (int(size[0]), int(size[1]))
            except Exception:
                pass

        with self._cv:
            self._last_jpeg = bytes(jpeg_bytes)
            self._cv.notify_all()

        self._update_fps(now)

    # ------------ Read API (MJPEG) ------------
    def get_jpeg_generator(self):
        """
        גנרטור של סטרים MJPEG: מחכה לעדכונים ומחזיר פריימים עטופים ב-boundary.
        """
        boundary = b"--frame"
        heartbeat_deadline = _safe_now() + 2.0

        while True:
            with self._cv:
                if self._last_jpeg is None:
                    self._cv.wait(timeout=0.5)
                data = self._last_jpeg

            if data is None:
                # אם אין עדיין פריים — דחוף placeholder פעם ב־2 שניות כדי לשמור חיבור חי
                if _safe_now() > heartbeat_deadline:
                    self._ensure_placeholder_jpeg()
                    heartbeat_deadline = _safe_now() + 2.0
                time.sleep(0.05)
                continue

            yield (
                boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            )

    # אליאס תאימות
    iter_mjpeg = get_jpeg_generator

    # ------------ Payload bridge (דוגמה; אופציונלי) ------------
    def push_payload(self, pixels: Dict[str, Any], metrics: Dict[str, Any], ts: Optional[float] = None) -> None:
        """
        אם יש לך שכבת זיכרון-שיתופי (admin_web.state.set_payload) — זה דוחף לשם.
        """
        try:
            from admin_web.state import set_payload  # type: ignore
        except Exception:
            set_payload = None  # type: ignore

        if set_payload:
            try:
                payload = {
                    "ts": float(ts) if ts is not None else _safe_now(),
                    "pixels": pixels or {},
                    "metrics": metrics or {},
                }
                set_payload(payload)  # type: ignore
            except Exception:
                pass

    # ------------ Freeze controls (אופציונלי; תאימות API) ------------
    def _set_freeze_flag(self, freeze: bool):
        prev = self._frozen
        self._frozen = bool(freeze)
        if not self._frozen:
            self._freeze_until = None
        if self.on_freeze_change and (prev != self._frozen):
            try:
                self.on_freeze_change(self._frozen)  # type: ignore
            except Exception:
                pass

    def set_freeze(self, freeze: bool):
        self._freeze_until = None
        self._set_freeze_flag(freeze)

    def freeze_for(self, seconds: float):
        secs = max(0.1, float(seconds))
        self._freeze_until = _safe_now() + secs
        self._set_freeze_flag(True)

    # ------------ Preview window (no-op) ------------
    def enable_preview(self, on: bool):
        # אין Preview ללא OpenCV — no-op
        return

    # ------------ Auto capture (ללא OpenCV — no-op) ------------
    def start_auto_capture(self):
        # אין פתיחת מצלמה בצד השרת — עובדים רק עם ingest מהדפדפן
        self._source_desc = "ingest-only"
        self._ensure_placeholder_jpeg()
        return

    def stop_auto_capture(self):
        self._running = False
        self._opened = False

    # ------------ Internals ------------
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


# ---- Global singleton ----
_streamer: Optional[VideoStreamer] = None

def get_streamer() -> VideoStreamer:
    """
    מחזיר סינגלטון של הסטרימר (ingest-only).
    """
    global _streamer
    if _streamer is None:
        cam = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))
        w = int(os.getenv("WIDTH", "1280"))
        h = int(os.getenv("HEIGHT", "720"))
        fps = int(os.getenv("FPS", "30"))
        q = int(os.getenv("JPEG_QUALITY", "70"))
        _streamer = VideoStreamer(cam, w, h, fps, q, False)
    return _streamer
