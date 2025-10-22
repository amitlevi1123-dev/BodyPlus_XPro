# app/ui/video.py
# -------------------------------------------------------
# 🎥 VideoStreamer + VideoWindow (safe, headless-friendly, MJPEG-ready)
# -------------------------------------------------------
from __future__ import annotations
import os, time, threading
from typing import Optional, Callable, Tuple, List, Dict, Any

# ---- Optional deps cv2/numpy (עשוי להיות חסר בפרוסס האדמין) ----
try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    CV2_OK = True
except Exception:  # fallback headless mode
    cv2 = None      # type: ignore
    np = None       # type: ignore
    CV2_OK = False

# ---- Bridge to admin_web.state (payload RAM-side) ----
try:
    from admin_web.state import set_payload  # type: ignore
except Exception:
    def set_payload(_p: Dict[str, Any]) -> None:
        pass

# ============================== Styling ==============================
PRIMARY       = (255, 182,  56)  # BGR
TEXT_DARK     = ( 36,  36,  36)
WHITE         = (255, 255, 255)
BLACK         = (  0,   0,   0)
BTN_BG        = (246, 248, 252)
BTN_BG_HOVER  = (240, 244, 252)
BTN_BG_ACTIVE = (255, 235, 200)
BORDER        = (120, 120, 120)

BAR_BG        = (  0,   0,   0)
BAR_ALPHA     = 0.25
BAR_H         = 64
BTN_W, BTN_H  = 170, 44
BTN_PAD, BTN_Y = 10, 12
RADIUS        = 16

FONT   = cv2.FONT_HERSHEY_SIMPLEX if CV2_OK else 0
FS_BTN = 0.55
FS_HINT= 0.52
FS_STAT= 0.60
KEY_HINT = "ESC Close   •   F Freeze   •   U Unfreeze   •   T Freeze 5s   •   M Metrics"

def _safe_now() -> float:
    try:
        return time.time()
    except Exception:
        return float(int(time.time()))

# ============================== Draw Helpers ==============================
def _draw_blend_rect(frame, x1, y1, x2, y2, color, alpha=0.35):
    if not CV2_OK: return
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, thickness=-1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

def _draw_pill(frame, x1, y1, x2, y2, fill, border=None, thickness=1, alpha=1.0):
    if not CV2_OK: return
    w = max(0, x2 - x1); h = max(0, y2 - y1); r = min(RADIUS, h // 2, w // 2)
    if alpha < 1.0:
        base = frame.copy()
        cv2.rectangle(base, (x1 + r, y1), (x2 - r, y2), fill, -1)
        cv2.circle(base, (x1 + r, y1 + r), r, fill, -1)
        cv2.circle(base, (x2 - r, y1 + r), r, fill, -1)
        cv2.addWeighted(base, alpha, frame, 1 - alpha, 0, frame)
    else:
        cv2.rectangle(frame, (x1 + r, y1), (x2 - r, y2), fill, -1)
        cv2.circle(frame, (x1 + r, y1 + r), r, fill, -1)
        cv2.circle(frame, (x2 - r, y1 + r), r, fill, -1)
    if border is not None and thickness > 0:
        cv2.ellipse(frame, (x1 + r, y1 + r), (r, r), 180, 0, 180, border, thickness)
        cv2.ellipse(frame, (x2 - r, y1 + r), (r, r),   0, 0, 180, border, thickness)
        cv2.line(frame, (x1 + r, y1), (x2 - r, y1), border, thickness)
        cv2.line(frame, (x1 + r, y2), (x2 - r, y2), border, thickness)

def _put_centered_text(frame, rect, text, fs=FS_BTN, color=TEXT_DARK, thick=1):
    if not CV2_OK: return
    x1, y1, x2, y2 = rect
    (tw, th), _ = cv2.getTextSize(text, FONT, fs, thick)
    cx = x1 + (x2 - x1 - tw) // 2
    cy = y1 + (y2 - y1 + th) // 2 - 2
    cv2.putText(frame, text, (cx, cy), FONT, fs, color, thick, cv2.LINE_AA)

def _put_text(frame, x, y, text, fs=FS_HINT, color=WHITE, thick=1):
    if not CV2_OK: return
    cv2.putText(frame, text, (x, y), FONT, fs, color, thick, cv2.LINE_AA)

# ============================== Core Streamer ==============================
class VideoStreamer:
    """
    Safe streamer (יציב לריסטים) שמייצר MJPEG, ומאפשר חיבור/ניתוק מצלמה בצורה קשיחה.
    עכשיו כולל ויסות קצב קריאה מהמצלמה (STREAM_FPS) וקצב קידוד MJPEG (MJPEG_FPS).
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

        # --- NEW: ויסות קצבים ---
        self.target_fps: int = int(os.getenv("STREAM_FPS", str(self.fps)))            # קצב קריאה מהמצלמה
        self.encode_fps: int = int(os.getenv("MJPEG_FPS", str(min(self.fps, 15))))    # קצב קידוד MJPEG
        self._next_capture_due: float = 0.0
        self._next_encode_due: float = 0.0
        self._decimation: int = max(1, int(os.getenv("STREAM_DECIMATION", "1")))
        self._decim_counter: int = 0

        # storage & sync
        self._last_jpeg: Optional[bytes] = None
        self._last_bgr = None
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)

        # status
        self._opened = False
        self._running = False
        self._last_size: Optional[Tuple[int, int]] = None
        self._last_push_ts = 0.0
        self._light_mode = "normal"
        self._source_desc = None
        self._fps_win: List[float] = []
        self._last_fps = None

        # preview
        self._preview = bool(show_preview_default)
        self._preview_thread: Optional[threading.Thread] = None

        # freeze
        self._frozen = False
        self._freeze_until: Optional[float] = None

        # callbacks
        self.on_open_metrics: Optional[Callable[[], None]] = None
        self.on_freeze_change: Optional[Callable[[bool], None]] = None

        # capture
        self._cap: Optional["cv2.VideoCapture"] = None
        self._cap_thread: Optional[threading.Thread] = None
        self._cap_lock = threading.Lock()

        if os.getenv("AUTO_CAPTURE", "0") == "1":
            self.start_auto_capture()

    # ------------ Status ------------
    def is_open(self) -> bool:    return bool(self._opened)
    def is_running(self) -> bool: return bool(self._running)
    def last_fps(self) -> Optional[float]:
        return float(self._last_fps) if self._last_fps is not None else None
    def last_frame_size(self) -> Optional[Tuple[int, int]]:
        return tuple(self._last_size) if self._last_size else None
    def get_light_mode(self) -> str: return self._light_mode
    def source_desc(self) -> Optional[str]: return self._source_desc

    # ------------ Capability helpers (ל־routes) ------------
    def get_camera_settings(self) -> Dict[str, int]:
        """החזרת הגדרות נוכחיות (best-effort)."""
        if CV2_OK and self._cap is not None:
            try:
                w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.width)
                h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)
                f = int(self._cap.get(cv2.CAP_PROP_FPS)          or self.fps)
                return {"width": w, "height": h, "fps": f}
            except Exception:
                pass
        return {"width": int(self.width), "height": int(self.height), "fps": int(self.fps)}

    def get_cap(self):
        """חשיפה אופציונלית ל־camera_controller."""
        return self._cap

    # ---------- new helper: set_resolution ----------
    def set_resolution(self, width: int, height: int) -> None:
        """
        עדכון מהיר של width/height פנימיים. אם יש OpenCV ו־cap פתוח, מנסה ליישם live.
        אחרת פשוט מעדכן את השדות (headless).
        """
        try:
            w = int(width); h = int(height)
        except Exception:
            return
        self.width, self.height = w, h
        # עדכון last_size לטובת UI
        self._last_size = (w, h)
        # אם אפשר — נסה ליישם live
        if CV2_OK and self._cap is not None:
            try:
                with self._cap_lock:
                    self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(self.width))
                    self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
                    # קרא חזרה
                    cur_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.width)
                    cur_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)
                    self.width, self.height = cur_w, cur_h
                    self._last_size = (cur_w, cur_h)
            except Exception:
                pass

    def apply_camera_settings(self, *, fps: Optional[int] = None,
                                       width: Optional[int] = None,
                                       height: Optional[int] = None) -> Tuple[bool, str]:
        """
        ננסה ליישם חי; אם אין CV2 או שהמצלמה לא פתוחה — נשמור ערכים לסטרט הבא
        אך עכשיו: גם ב־headless נחזיר ok=True (applied_headless) לאחר עדכון הפנימיים,
        כדי לא לדרוש restart דרך ה-route. אם יש OpenCV ו-cap פתוח — ננסה live-apply כרגיל.
        """
        # עדכון פנימי תמיד
        if fps   is not None:
            try: self.fps = int(fps)
            except Exception: pass
        if width is not None:
            try: self.width = int(width)
            except Exception: pass
        if height is not None:
            try: self.height = int(height)
            except Exception: pass

        # עדכון last_size לטובת UI
        self._last_size = (int(self.width), int(self.height))

        # אם אין יכולת live-apply — עדכון פנימי מספיק (headless)
        if (not CV2_OK) or (self._cap is None):
            # נשמור ונחזיר שהוחל (headless)
            return (True, "applied_headless")

        # יש CV2 & cap — נסה ליישם live
        ok_all = True
        msg_parts: List[str] = []
        with self._cap_lock:
            try:
                if width  is not None: self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(self.width))
                if height is not None: self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self.height))
                if fps    is not None: self._cap.set(cv2.CAP_PROP_FPS,          float(self.fps))

                cur_w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)  or self.width)
                cur_h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height)
                cur_f = int(self._cap.get(cv2.CAP_PROP_FPS)          or self.fps)

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

    # ------------ Run-time controls ------------
    def set_target_fps(self, fps: int) -> None:
        try:
            v = int(fps)
            if v > 0:
                self.target_fps = v
        except Exception:
            pass

    def set_decimation(self, n: int) -> None:
        try:
            v = max(1, int(n))
            self._decimation = v
        except Exception:
            pass

    # ------------ Public ingest (למדידות/MediaPipe) ------------
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

        # מצערת קידוד MJPEG
        if (not self._frozen) and (self._freeze_until is None):
            if frame is not None and CV2_OK:
                if self.encode_fps > 0:
                    if now >= self._next_encode_due:
                        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)])
                        if ok:
                            with self._cv:
                                self._last_jpeg = buf.tobytes()
                                self._cv.notify_all()
                        self._next_encode_due = now + (1.0 / float(self.encode_fps))
                else:
                    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(self.jpeg_quality)])
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
            img = np.zeros((1, 1, 3), dtype=np.uint8)
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

    def iter_mjpeg(self):
        return self.get_jpeg_generator()

    # ------------ Payload bridge ------------
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

    def push_mediapipe_pose(self, landmarks, frame_w: int, frame_h: int,
                            metrics: Optional[Dict[str, Any]] = None,
                            ts: Optional[float] = None) -> None:
        try:
            def pt(idx):
                lm = landmarks[idx]
                return [float(lm.x) * frame_w, float(lm.y) * frame_h]
            pixels = {
                "shoulder_left":  pt(11), "shoulder_right": pt(12),
                "elbow_left":     pt(13), "elbow_right":    pt(14),
                "wrist_left":     pt(15), "wrist_right":    pt(16),
                "hip_left":       pt(23), "hip_right":      pt(24),
                "knee_left":      pt(25), "knee_right":     pt(26),
                "ankle_left":     pt(27), "ankle_right":    pt(28),
            }
            self.push_payload(pixels=pixels, metrics=metrics or {}, ts=ts)
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

    # ------------ Preview window (optional) ------------
    def enable_preview(self, on: bool):
        if not CV2_OK:
            return
        self._preview = bool(on)
        if on and (self._preview_thread is None or not self._preview_thread.is_alive()):
            self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
            self._preview_thread.start()
        if not on:
            try: cv2.destroyWindow(self.window_name)
            except Exception: pass

    def _on_mouse(self, event, x, y, _flags, _param):
        self._mouse_xy = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self._click_xy = (x, y)

    def _add_button(self, x, y, label, cb):
        x1, y1 = x, y; x2, y2 = x + BTN_W, y + BTN_H
        self._buttons.append((x1, y1, x2, y2, label, cb))

    def _button_rects(self, start_x, start_y):
        self._buttons: List[Tuple[int,int,int,int,str,Callable]] = []
        x, y = start_x, start_y
        self._add_button(x, y, "Metrics",   self._open_metrics); x += BTN_W + BTN_PAD
        self._add_button(x, y, "Freeze",    lambda: self.set_freeze(True)); x += BTN_W + BTN_PAD
        self._add_button(x, y, "Unfreeze",  lambda: self.set_freeze(False)); x += BTN_W + BTN_PAD
        self._add_button(x, y, "Freeze 5s", lambda: self.freeze_for(5));    x += BTN_W + BTN_PAD
        return self._buttons

    def _draw_top_bar(self, frame):
        _draw_blend_rect(frame, 0, 0, frame.shape[1], BAR_H, BAR_BG, alpha=BAR_ALPHA)
        status_text  = "FROZEN" if (self._frozen or self._freeze_until is not None) else "ACTIVE"
        status_color = ( 50, 220,  50) if status_text == "ACTIVE" else ( 40,  80, 255)
        dot_x, dot_y = frame.shape[1] - 180, 22
        if CV2_OK:
            cv2.circle(frame, (dot_x, dot_y), 6, status_color, -1)
            _put_text(frame, dot_x + 14, 27, status_text, fs=FS_STAT, color=WHITE, thick=1)

    def _draw_buttons(self, frame):
        rects = self._button_rects(BTN_PAD, BTN_Y)
        mx, my = getattr(self, "_mouse_xy", (-1, -1))
        for (x1, y1, x2, y2, label, cb) in rects:
            active   = (label == "Freeze") and (self._frozen or self._freeze_until is not None)
            hovering = (x1 <= mx <= x2 and y1 <= my <= y2)
            bg       = BTN_BG_ACTIVE if active else (BTN_BG_HOVER if hovering else BTN_BG)
            border   = PRIMARY if hovering or active else BORDER
            _draw_pill(frame, x1, y1, x2, y2, bg, border, thickness=1, alpha=1.0)
            _put_centered_text(frame, (x1, y1, x2, y2), label, fs=FS_BTN, color=TEXT_DARK, thick=1)

    def _draw_key_hints(self, frame):
        _put_text(frame, 18, BAR_H - 10, KEY_HINT, fs=FS_HINT, color=WHITE, thick=1)

    def _handle_click(self):
        click_xy = getattr(self, "_click_xy", None)
        if click_xy is None:
            return
        cx, cy = click_xy
        self._click_xy = None
        for (x1, y1, x2, y2, _label, cb) in getattr(self, "_buttons", []):
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                try: cb()
                except Exception: pass
                break

    def _open_metrics(self):
        cb = self.on_open_metrics
        if callable(cb):
            try: cb()
            except Exception: pass

    def _preview_loop(self):
        if not CV2_OK:
            return
        self._buttons: List[Tuple[int,int,int,int,str,Callable]] = []
        self._click_xy = None; self._mouse_xy = None
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, 1120, 640)
        cv2.setMouseCallback(self.window_name, self._on_mouse)
        try:
            while self._preview:
                if self._last_bgr is None:
                    cv2.waitKey(10); continue
                frame = self._last_bgr.copy()
                self._draw_top_bar(frame)
                self._draw_buttons(frame)
                self._draw_key_hints(frame)
                self._handle_click()
                cv2.imshow(self.window_name, frame)
                k = cv2.waitKey(1) & 0xFF
                if k == 27: self._preview = False; break
                elif k in (ord('f'), ord('F')): self.set_freeze(True)
                elif k in (ord('u'), ord('U')): self.set_freeze(False)
                elif k in (ord('t'), ord('T')): self.freeze_for(5)
                elif k in (ord('m'), ord('M')): self._open_metrics()
        finally:
            try: cv2.destroyWindow(self.window_name)
            except Exception: pass

    # ------------ Auto capture (paced) ------------
    def start_auto_capture(self):
        if not CV2_OK:
            self._source_desc = "headless/none"
            return
        if self._cap_thread is not None and not self._cap_thread.is_alive():
            self._cap_thread = None
        if self._cap_thread is not None:
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
        if not CV2_OK:
            return None
        backends = [(cv2.CAP_DSHOW, "dshow"), (cv2.CAP_MSMF, "msmf"), (0, "default")]
        for be, name in backends:
            cap = None
            try:
                cap = cv2.VideoCapture(self.camera_index, be) if be != 0 else cv2.VideoCapture(self.camera_index)
                if cap.isOpened():
                    self._source_desc = f"camera:{self.camera_index}({name})"
                    return cap
                if cap is not None:
                    cap.release()
            except Exception:
                if cap is not None:
                    try: cap.release()
                    except Exception: pass
        return None

    def _capture_loop(self):
        if not CV2_OK:
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
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS,          self.fps)

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
                h, w = self.height, self.width
                img = np.zeros((h, w, 3), dtype=np.uint8)
                img[:] = (20, 20, 20)
                msg = "NO INPUT – waiting for frames"
                cv2.putText(img, msg, (30, 80), FONT, 1.0, (200, 200, 200), 2, cv2.LINE_AA)
                ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    self._last_size = (w, h)
                    self._last_jpeg = buf.tobytes()
                    return
            self._last_jpeg = _MIN_JPEG_FALLBACK
        except Exception:
            self._last_jpeg = _MIN_JPEG_FALLBACK

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

# ============================== Legacy VideoWindow ==============================
class _DummyWin:
    def __init__(self, on_close: Optional[Callable] = None):
        self._on_close = on_close
    def protocol(self, name: str, func: Callable):
        if name == "WM_DELETE_WINDOW":
            self._on_close = func
    def call_close(self):
        if callable(self._on_close):
            try: self._on_close()
            except Exception: pass

class VideoWindow:
    """Legacy-compat window (לא פותח מצלמה — רק מציג פריימים קיימים ונדחף ל־MJPEG)."""
    def __init__(self, title: str = "OpenCV Preview", width: int = 960, height: int = 540):
        self._title = title or "OpenCV Preview"
        self._size = (int(width), int(height))
        self._visible = False
        self.win = _DummyWin(on_close=self._on_external_close)

    @property
    def title(self) -> str: return self._title

    def set_title(self, title: str):
        self._title = title or self._title
        if self._visible and CV2_OK:
            try: cv2.destroyWindow(self._title)
            except Exception: pass
            self._visible = False
            self.show()

    def resize(self, width: int, height: int):
        self._size = (int(width), int(height))
        if self._visible and CV2_OK:
            try: cv2.resizeWindow(self._title, *self._size)
            except Exception: pass

    def show(self):
        if not CV2_OK:
            self._visible = True; return
        try:
            cv2.namedWindow(self._title, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(self._title, *self._size)
            self._visible = True
        except Exception:
            self._visible = False

    def _on_external_close(self):
        if CV2_OK:
            try: cv2.destroyWindow(self._title)
            except Exception: pass
        self._visible = False

    close = _on_external_close
    hide  = _on_external_close
    stop  = _on_external_close

    def imshow(self, frame):
        if frame is None:
            return
        try:
            get_streamer().push_bgr_frame(frame)
        except Exception:
            pass
        if not CV2_OK:
            return
        if not self._visible:
            self.show()
        try:
            cv2.imshow(self._title, frame)
            prop = cv2.getWindowProperty(self._title, cv2.WND_PROP_VISIBLE)
            if prop < 1:
                self._visible = False
                try: cv2.destroyWindow(self._title)
                except Exception: pass
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                self.close()
        except Exception:
            self._visible = False
            try: cv2.destroyWindow(self._title)
            except Exception: pass

    def update_frame(self, frame): self.imshow(frame)
    def update(self, frame):       self.imshow(frame)

# ---- 1x1 minimal JPEG (fallback if cv2 is unavailable everywhere) ----
_MIN_JPEG_FALLBACK = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08"*64 +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
)
