# -*- coding: utf-8 -*-
"""
app/ui/video.py
--------------------------------------------
🎥 VideoStreamer — סטרימר MJPEG יציב:
- ingest_jpeg(jpeg_bytes) להזנת פריימים מהדפדפן/טלפון לפייפליין.
- push_bgr_frame/push_jpeg לעדכון הפריים האחרון + יצירת JPEG.
- get_jpeg_generator() להזרמת MJPEG.

⚠️ בטוח לענן:
- לא פותח מצלמה בזמן import.
- אם אין /dev/video0 או NO_CAMERA=1 → לא ינסה לפתוח מצלמה בכלל.
- תצוגת OpenCV Preview לא מופעלת בענן (no-op אם CV2 לא זמין/NO_CAMERA=1).
"""

from __future__ import annotations
import os, time, threading, io
from typing import Optional, Callable, Tuple, List, Dict, Any

# ---- Optional deps cv2/numpy/PIL ----
try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    CV2_OK = True
except Exception:
    cv2 = None      # type: ignore
    np = None       # type: ignore
    CV2_OK = False

try:
    from PIL import Image  # type: ignore
    PIL_OK = True
except Exception:
    Image = None  # type: ignore
    PIL_OK = False

# ---- Bridge to admin_web.state (payload RAM-side) ----
try:
    from admin_web.state import set_payload  # type: ignore
except Exception:
    def set_payload(_p: Dict[str, Any]) -> None:
        pass

# ---- Global camera guards (serverless safe) ----
_NO_CAM_ENV = (os.getenv("NO_CAMERA") == "1") or (not os.path.exists("/dev/video0"))
if _NO_CAM_ENV:
    os.environ.setdefault("NO_CAMERA", "1")
    # אם cv2 קיים, מחליף את VideoCapture ב-stub שלא ניגש ל-/dev/video0
    if CV2_OK:
        class _DummyCap:
            def __init__(self, *a, **k): pass
            def isOpened(self): return False
            def read(self): return False, None
            def release(self): pass
            def set(self, *a): return False
            def get(self, *a): return 0
        cv2.VideoCapture = _DummyCap  # type: ignore[attr-defined]
        try:
            # הורדת רעש לוגים של OpenCV (לא בכל גרסה קיים)
            cv2.setLogLevel(cv2.LOG_LEVEL_SILENT)  # type: ignore[attr-defined]
        except Exception:
            pass

# ============================== styling (אופציונלי) ==============================
PRIMARY       = (255, 182,  56)  # BGR
WHITE         = (255, 255, 255)
BLACK         = (  0,   0,   0)

FONT   = cv2.FONT_HERSHEY_SIMPLEX if CV2_OK else 0

def _safe_now() -> float:
    try:
        return time.time()
    except Exception:
        return float(int(time.time()))

# ============================== core streamer ==============================
class VideoStreamer:
    """
    סטרימר יציב שמייצר MJPEG. כולל ingest_jpeg(jpeg_bytes) לחיבור capture-דפדפן לפייפליין.
    בטוח לענן: לא יפתח מצלמה אם NO_CAMERA=1 או אם אין /dev/video0.
    """
    def __init__(self,
                 camera_index: int = 0,
                 width: int = 1280,
                 height: int = 720,
                 fps: int = 30,
                 jpeg_quality: int = 70,
                 show_preview_default: bool = False,
                 window_name: str = "OpenCV Preview"):
        self.camera_index = int(camera_index)
        self.width, self.height = int(width), int(height)
        self.fps, self.jpeg_quality = int(fps), int(jpeg_quality)
        self.window_name = window_name

        # קצבי עבודה
        self.target_fps: int = int(os.getenv("STREAM_FPS", str(self.fps)))
        self.encode_fps: int = int(os.getenv("MJPEG_FPS", str(min(self.fps, 15))))
        self._next_encode_due: float = 0.0
        self._decimation: int = max(1, int(os.getenv("STREAM_DECIMATION", "1")))
        self._decim_counter: int = 0

        # סטייט פריימים
        self._last_jpeg: Optional[bytes] = None
        self._last_bgr = None
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        # סטייט מצלמה/ריצה
        self._opened = False
        self._running = False
        self._last_size: Optional[Tuple[int, int]] = None
        self._last_push_ts = 0.0
        self._source_desc: Optional[str] = None
        self._fps_win: List[float] = []
        self._last_fps: Optional[float] = None

        # Freezing
        self._frozen = False
        self._freeze_until: Optional[float] = None

        # Hooks
        self.on_open_metrics: Optional[Callable[[], None]] = None
        self.on_freeze_change: Optional[Callable[[bool], None]] = None

        # Capture thread
        self._cap: Optional["cv2.VideoCapture"] = None
        self._cap_thread: Optional[threading.Thread] = None
        self._cap_lock = threading.Lock()

        # Preview (לא נדרש בענן; no-op אם אין CV2 או NO_CAMERA)
        self._preview = bool(show_preview_default)
        self._preview_thread: Optional[threading.Thread] = None

        # לא מפעילים AUTO_CAPTURE בענן. גם אם מוגדר, guard יחסום.
        if os.getenv("AUTO_CAPTURE", "0") == "1":
            self.start_auto_capture()

    # ------------ Status ------------
    def is_open(self) -> bool:    return bool(self._opened)
    def is_running(self) -> bool: return bool(self._running)
    def last_fps(self) -> Optional[float]:
        return float(self._last_fps) if self._last_fps is not None else None
    def last_frame_size(self) -> Optional[Tuple[int, int]]:
        return tuple(self._last_size) if self._last_size else None
    def get_light_mode(self) -> str: return "normal"
    def source_desc(self) -> Optional[str]: return self._source_desc

    # ------------ Camera settings helpers ------------
    def get_camera_settings(self) -> Dict[str, int]:
        if CV2_OK and self._cap is not None:
            try:
                w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.width)   # type: ignore[attr-defined]
                h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)  # type: ignore[attr-defined]
                f = int(self._cap.get(cv2.CAP_PROP_FPS)          or self.fps)     # type: ignore[attr-defined]
                return {"width": w, "height": h, "fps": f}
            except Exception:
                pass
        return {"width": int(self.width), "height": int(self.height), "fps": int(self.fps)}

    def set_resolution(self, width: int, height: int) -> None:
        try:
            w = int(width); h = int(height)
        except Exception:
            return
        self.width, self.height = w, h
        self._last_size = (w, h)
        if CV2_OK and self._cap is not None:
            try:
                with self._cap_lock:
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(self.width))   # type: ignore[attr-defined]
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))  # type: ignore[attr-defined]
                    cur_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.width)   # type: ignore[attr-defined]
                    cur_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)  # type: ignore[attr-defined]
                    self.width, self.height = cur_w, cur_h
                    self._last_size = (cur_w, cur_h)
            except Exception:
                pass

    def apply_camera_settings(self, *, fps: Optional[int] = None,
                                       width: Optional[int] = None,
                                       height: Optional[int] = None) -> Tuple[bool, str]:
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

        if (not CV2_OK) or (self._cap is None):
            return (True, "applied_headless")

        ok_all = True
        msg_parts: List[str] = []
        with self._cap_lock:
            try:
                if width  is not None: self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(self.width))   # type: ignore[attr-defined]
                if height is not None: self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))  # type: ignore[attr-defined]
                if fps    is not None: self._cap.set(cv2.CAP_PROP_FPS,          float(self.fps))     # type: ignore[attr-defined]

                cur_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.width)   # type: ignore[attr-defined]
                cur_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)  # type: ignore[attr-defined]
                cur_f = int(self._cap.get(cv2.CAP_PROP_FPS)          or self.fps)     # type: ignore[attr-defined]

                self.width, self.height, self.fps = cur_w, cur_h, cur_f
                self._last_size = (cur_w, cur_h)

                if width  is not None and abs(cur_w - int(width))   > 2: ok_all = False; msg_parts.append(f"width={cur_w}")
                if height is not None and abs(cur_h - int(height)) > 2: ok_all = False; msg_parts.append(f"height={cur_h}")
                if fps    is not None and abs(cur_f - int(fps))     > 1: ok_all = False; msg_parts.append(f"fps={cur_f}")

                if ok_all:
                    return (True, "applied_live")
                else:
                    return (False, "live_apply_partial:" + ",".join(msg_parts))
            except Exception as e:
                return (False, f"live_apply_error:{e!r}")

    # ------------ Public ingest bridge ------------
    def ingest_jpeg(self, jpeg_bytes: bytes) -> None:
        """
        לקבל JPEG מהשרת (ingest), לפענח, להזין לפייפליין, ולשמור להצגה.
        """
        frame_bgr = None
        try:
            if CV2_OK:
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)  # type: ignore
                frame_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)   # BGR
            elif PIL_OK:
                im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
                import numpy as _np  # lazy import רק אם צריך
                frame_bgr = _np.asarray(im)[:, :, ::-1]           # RGB→BGR
        except Exception:
            frame_bgr = None

        if frame_bgr is not None:
            self.push_bgr_frame(frame_bgr)
        else:
            self.push_jpeg(jpeg_bytes)

    # ------------ Push APIs ------------
    def push_bgr_frame(self, frame) -> None:
        now = _safe_now()
        self._opened = True
        self._running = True
        self._last_push_ts = now

        if frame is not None and CV2_OK:
            h, w = frame.shape[:2]
            self._last_size = (w, h)

        if self._freeze_until is not None and now >= self._freeze_until:
            self._freeze_until = None
            self._set_freeze_flag(False)

        self._last_bgr = frame

        if (not self._frozen) and (self._freeze_until is None):
            if frame is not None and CV2_OK:
                if self.encode_fps > 0:
                    if now >= self._next_encode_due:
                        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)])  # type: ignore[attr-defined]
                        if ok:
                            with self._cv:
                                self._last_jpeg = buf.tobytes()
                                self._cv.notify_all()
                        self._next_encode_due = now + (1.0 / float(self.encode_fps))
                else:
                    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)])  # type: ignore[attr-defined]
                    if ok:
                        with self._cv:
                            self._last_jpeg = buf.tobytes()
                            self._cv.notify_all()
            elif self._last_jpeg is None:
                self._ensure_placeholder_jpeg()

        self._update_fps(now)

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
            self._last_size = (int(size[0]), int(size[1]))
        with self._cv:
            self._last_jpeg = bytes(jpeg_bytes)
            self._cv.notify_all()
        self._update_fps(now)

    # ------------ Read API (MJPEG) ------------
    def read_frame(self) -> Tuple[bool, Optional["np.ndarray"]]:
        if not CV2_OK:
            return False, None
        frame = self._last_bgr
        if frame is None:
            img = np.zeros((1, 1, 3), dtype=np.uint8)  # type: ignore
            return True, img
        return True, frame

    def get_jpeg_generator(self):
        boundary = b"--frame"
        heartbeat_deadline = _safe_now() + 2.0
        while True:
            with self._cv:
                if self._last_jpeg is None:
                    self._cv.wait(timeout=0.5)
                data = self._last_jpeg
            if data is None:
                if _safe_now() > heartbeat_deadline:
                    self._ensure_placeholder_jpeg()
                    heartbeat_deadline = _safe_now() + 2.0
                time.sleep(0.05)
                continue
            yield boundary + b"\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"

    # alias
    iter_mjpeg = get_jpeg_generator

    # ------------ Payload bridge (דוגמא) ------------
    def push_payload(self, pixels: Dict[str, Any], metrics: Dict[str, Any], ts: Optional[float] = None) -> None:
        try:
            payload = {
                "ts": float(ts) if ts is not None else _safe_now(),
                "pixels": pixels or {},
                "metrics": metrics or {},
            }
            set_payload(payload)
        except Exception:
            pass

    # ------------ Freeze controls ------------
    def _set_freeze_flag(self, freeze: bool):
        prev = self._frozen
        self._frozen = bool(freeze)
        if not self._frozen:
            self._freeze_until = None
        if self.on_freeze_change and (prev != self._frozen):
            try: self.on_freeze_change(self._frozen)
            except Exception: pass

    def set_freeze(self, freeze: bool):
        self._freeze_until = None
        self._set_freeze_flag(freeze)

    def freeze_for(self, seconds: float):
        secs = max(0.1, float(seconds))
        self._freeze_until = _safe_now() + secs
        self._set_freeze_flag(True)

    # ------------ Preview window (optional; no-op בענן) ------------
    def enable_preview(self, on: bool):
        # לא פותחים חלון בענן. רק בלוקאל, כשהכול זמין ואין NO_CAMERA.
        if not CV2_OK or os.getenv("NO_CAMERA") == "1":
            return
        self._preview = bool(on)
        if not on:
            try: cv2.destroyWindow(self.window_name)  # type: ignore
            except Exception: pass

    # ------------ Auto capture (מצלמה מקומית בלבד) ------------
    def start_auto_capture(self):
        # Guard: אל תפתח מצלמה בענן/ללא התקן
        if os.getenv("NO_CAMERA") == "1" or (not os.path.exists("/dev/video0")) or (not CV2_OK):
            self._source_desc = "headless/none"
            self._ensure_placeholder_jpeg()
            return
        if self._cap_thread is not None and self._cap_thread.is_alive():
            return
        self._cap_thread = threading.Thread(target=self._capture_loop, daemon=True, name="VideoCaptureLoop")
        self._cap_thread.start()

    def stop_auto_capture(self):
        self._running = False
        t = self._cap_thread
        if t is not None and t.is_alive():
            t.join(timeout=1.5)
        self._cap_thread = None
        self._opened = False

    def _open_cap(self):
        if os.getenv("NO_CAMERA") == "1" or (not os.path.exists("/dev/video0")) or (not CV2_OK):
            return None
        # נסה backends שונים (בלינוקס/מק/ווינדוס)
        backends = [
            # לינוקס/דיפולט
            (0, "default"),
        ]
        cap = None
        for be, name in backends:
            try:
                cap = cv2.VideoCapture(self.camera_index) if be == 0 else cv2.VideoCapture(self.camera_index, be)  # type: ignore
                if cap is not None and cap.isOpened():
                    self._source_desc = f"camera:{self.camera_index}({name})"
                    return cap
                if cap is not None:
                    cap.release()
            except Exception:
                if cap is not None:
                    try: cap.release()
                    except Exception: pass
                cap = None
        return None

    def _capture_loop(self):
        if os.getenv("NO_CAMERA") == "1" or (not os.path.exists("/dev/video0")) or (not CV2_OK):
            return
        self._running = True
        cap = self._open_cap()
        with self._cap_lock:
            self._cap = cap
        if cap is None:
            self._running = False
            self._opened = False
            self._ensure_placeholder_jpeg()
            self._source_desc = f"camera:{self.camera_index}(unavailable)"
            return

        self._opened = True
        try:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)   # type: ignore[attr-defined]
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)  # type: ignore[attr-defined]
            cap.set(cv2.CAP_PROP_FPS,          self.fps)     # type: ignore[attr-defined]
        except Exception:
            pass

        next_due = _safe_now()
        try:
            while self._running:
                if self.target_fps > 0:
                    now = _safe_now()
                    if now < next_due:
                        time.sleep(max(0.0, next_due - now))
                    next_due = now + (1.0 / float(self.target_fps))

                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.01)
                    continue

                self._decim_counter = (self._decim_counter + 1) % self._decimation
                if self._decim_counter != 0:
                    self._last_bgr = frame
                    continue

                self.push_bgr_frame(frame)
        finally:
            try:
                cap.release()
            except Exception:
                pass
            with self._cap_lock:
                self._cap = None
            self._running = False
            self._opened = False

    # ------------ Internals ------------
    def _ensure_placeholder_jpeg(self):
        if self._last_jpeg is not None:
            return
        try:
            if CV2_OK and np is not None:
                h, w = max(1, int(self.height)), max(1, int(self.width))
                img = np.zeros((h, w, 3), dtype=np.uint8)  # type: ignore
                img[:] = (20, 20, 20)
                msg = "NO INPUT – waiting for frames"
                try:
                    cv2.putText(img, msg, (30, 80), FONT, 1.0, (200, 200, 200), 2, cv2.LINE_AA)  # type: ignore
                except Exception:
                    pass
                ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])  # type: ignore[attr-defined]
                if ok:
                    self._last_size = (w, h)
                    self._last_jpeg = buf.tobytes()
                    return
        except Exception:
            pass
        # מינימום 1×1 — JPEG קטן תקני
        self._last_jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
            b"\xff\xdb\x00C\x00" + b"\x08"*64 +
            b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
            b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
        )

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
    global _streamer
    if _streamer is None:
        cam = int(os.getenv("CAMERA_INDEX", os.getenv("OBJDET_CAMERA_INDEX", "0")))
        w = int(os.getenv("WIDTH", "1280"))
        h = int(os.getenv("HEIGHT", "720"))
        fps = int(os.getenv("FPS", "30"))
        q = int(os.getenv("JPEG_QUALITY", "70"))
        _streamer = VideoStreamer(cam, w, h, fps, q, False)
    return _streamer
