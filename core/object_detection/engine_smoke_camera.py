# core/object_detection/engine_smoke_camera.py
# -------------------------------------------------------
# 🎥 Smoke Test יציב למודול זיהוי אובייקט (DevNull/Roboflow/YOLO)
#
# יכולות:
# • Single-instance lock (כדי שלא ייפתחו שני חלונות).
# • פתיחת מצלמה יציבה (MJPG, המרת RGB, נסיונות ברזולוציות שונות).
# • לולאה: update_frame → tick, ציור תיבות/מרכז/זווית + שכבת מידע.
# • יציאה: q / ESC / סגירת חלון (X).
# • ניקוי משאבים בטוח גם אם יש חריגות.
# -------------------------------------------------------

from __future__ import annotations
import os
import sys
import time
import atexit
import signal
import tempfile
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

# הבטחת PYTHONPATH גם בהרצות יחסיות
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# לוגים
try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def info(self, *a, **k): ...
        def warning(self, *a, **k): ...
        def error(self, *a, **k): ...
    logger = _NullLogger()  # type: ignore

# ייבוא מנוע
try:
    from .engine import ObjectDetectionEngine
except Exception:
    from core.object_detection.engine import ObjectDetectionEngine  # type: ignore

# פרמטרים מהסביבה
YAML_PATH = os.environ.get("OBJDET_YAML", "core/object_detection/object_detection.yaml")
CAM_INDEX = int(os.environ.get("OBJDET_CAM", "0"))

WINDOW_NAME = "ObjectDetection — Smoke Camera"
_lock_file_handle: Optional[int] = None
_cap: Optional[cv2.VideoCapture] = None
_eng: Optional[ObjectDetectionEngine] = None


# ------------------------- Single Instance Lock -------------------------

def _acquire_single_instance_lock() -> None:
    """מונע כמה הרצות מקבילות (כדי שלא ייפתחו שני חלונות)."""
    global _lock_file_handle
    lock_path = os.path.join(tempfile.gettempdir(), "bodyplus_xpro_smoke.lock")
    try:
        # פתיחה אקסקלוסיבית; תיכשל אם קיים
        _lock_file_handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.write(_lock_file_handle, str(os.getpid()).encode("utf-8"))
        logger.info("acquired single-instance lock at {}", lock_path)

        def _cleanup_lock():
            try:
                if _lock_file_handle is not None:
                    os.close(_lock_file_handle)
                if os.path.exists(lock_path):
                    os.remove(lock_path)
            except Exception:
                pass
        atexit.register(_cleanup_lock)
    except FileExistsError:
        logger.warning("Another smoke-camera instance is already running. Exiting.")
        sys.exit(0)


# ---------------------------- Cleanup Handling --------------------------

def _cleanup():
    """ניקוי בטוח של משאבים (מצלמה/חלונות/מנוע)."""
    global _cap, _eng
    try:
        if _cap is not None:
            _cap.release()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass
    try:
        if _eng is not None:
            _eng.stop()
    except Exception:
        pass

def _install_signal_handlers():
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, lambda *_: (_cleanup(), sys.exit(0)))
        except Exception:
            pass
    atexit.register(_cleanup)


# ----------------------------- Drawing utils ----------------------------

def _draw_tracks(frame: np.ndarray, tracks: List[Any]) -> None:
    """ציור תיבות/מרכז/זווית על הפריים; תומך גם באובייקטים וגם ב-dict."""
    if not tracks:
        return
    for t in tracks:
        def get(field, default=None):
            return getattr(t, field, default) if hasattr(t, field) else (
                t.get(field, default) if isinstance(t, dict) else default
            )
        box = get("box")
        x1 = y1 = None
        if box and len(box) == 4:
            x1, y1, x2, y2 = [int(v) for v in box]
            cv2.rectangle(frame, (x1, y1), (x2, y2), (180, 120, 30), 2)

        cx, cy = get("cx"), get("cy")
        if cx is not None and cy is not None:
            cv2.circle(frame, (int(cx), int(cy)), 4, (30, 200, 255), -1)

        angle = get("angle_deg")
        label = get("label", "?")
        tid = get("track_id", get("id", "-"))
        txt = f"{label}#{tid}"
        if angle is not None:
            try:
                txt += f"  {float(angle):.1f}°"
            except Exception:
                txt += f"  {angle}°"

        org = (x1 if x1 is not None else 10, (y1 - 6) if y1 is not None else 22)
        cv2.putText(frame, txt, org, cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 200, 255), 2, cv2.LINE_AA)


# ------------------------------ Camera utils ----------------------------

def _flush_frames(cap: cv2.VideoCapture, n: int = 8) -> Optional[np.ndarray]:
    last = None
    for _ in range(max(1, n)):
        ok, frm = cap.read()
        if ok and frm is not None and frm.size > 0:
            last = frm
        cv2.waitKey(1)
    return last

def _open_camera(index: int) -> Optional[cv2.VideoCapture]:
    """פותח מצלמה בצורה יציבה על Windows: המרת RGB + MJPG + נסיונות רזולוציה."""
    backends = (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY)
    for backend in backends:
        try:
            cap = cv2.VideoCapture(index, backend)
            if not cap.isOpened():
                cap.release()
                continue

            # ודא המרה ל-BGR
            cap.set(cv2.CAP_PROP_CONVERT_RGB, 1)

            # בקש MJPG (מונע מסך שחור ב-YUY2)
            try:
                fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                cap.set(cv2.CAP_PROP_FOURCC, fourcc)
            except Exception:
                pass

            for (w, h) in [(1280, 720), (960, 540), (640, 480)]:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                cap.set(cv2.CAP_PROP_FPS, 30)
                frm = _flush_frames(cap, 10)
                if frm is not None and frm.mean() > 1:
                    logger.info("camera {} opened with backend {} at {}x{}", index, backend, w, h)
                    return cap

            cap.release()
        except Exception:
            try:
                cap.release()
            except Exception:
                pass
    return None


# --------------------------------- Main ---------------------------------

def main() -> None:
    global _cap, _eng
    _acquire_single_instance_lock()
    _install_signal_handlers()

    # נוודא שאין חלונות פתוחים מלפני (אם הרצה קודמת נפלה)
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass

    logger.info("[smoke] using YAML: {}", YAML_PATH)
    try:
        _eng = ObjectDetectionEngine.from_yaml(YAML_PATH)
    except Exception as e:
        logger.error("[smoke] engine init failed: {}", e)
        return

    try:
        _eng.start()
    except Exception as e:
        logger.warning("[smoke] eng.start failed (continuing): {}", e)

    _cap = _open_camera(CAM_INDEX)
    if not _cap:
        logger.warning("[smoke] camera open failed; running loop without frames")

    paused = False
    last_t = time.time()
    fps: float = 0.0

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    logger.info("[smoke] ready. press 'q' or ESC to quit, 'space' to pause/resume.")

    try:
        while True:
            # אפשר לצאת גם בלחיצה על X של החלון
            try:
                vis_prop = cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE)
                if vis_prop < 1:  # נסגר ע"י המשתמש
                    break
            except Exception:
                # אם אין חלון (נזרקה שגיאה) — נצא
                break

            frame = None
            if not paused and _cap and _cap.isOpened():
                ok, f = False, None
                try:
                    ok, f = _cap.read()
                except Exception:
                    ok = False
                if ok and f is not None:
                    frame = f

            # עדכון פריים (אם קיים)
            if frame is not None and _eng is not None:
                try:
                    _eng.update_frame(frame)
                except Exception as e:
                    logger.warning("[smoke] update_frame failed: {}", e)

            # מחזור עיבוד
            try:
                tracks, payload = _eng.tick() if _eng is not None else ([], {})
            except Exception as e:
                logger.error("[smoke] eng.tick failed: {}", e)
                tracks, payload = [], {"detector_state": {"ok": False, "last_error": str(e)}, "objects": []}

            # UI
            if frame is None:
                canvas = np.zeros((360, 640, 3), dtype="uint8")
                msg = "PAUSED" if paused else "NO CAMERA"
                cv2.putText(canvas, f"{msg} — press SPACE", (20, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW_NAME, canvas)
            else:
                vis = frame.copy()
                _draw_tracks(vis, tracks)

                # FPS מחושב בהחלקה
                now = time.time()
                dt = max(1e-6, now - last_t)
                last_t = now
                fps = 0.85 * fps + 0.15 * (1.0 / dt)

                st = payload.get("detector_state", {}) if isinstance(payload, dict) else {}
                ok_flag = bool(st.get("ok", True))
                prov = st.get("provider", "?")

                cv2.putText(vis, f"FPS ~ {fps:.1f}", (10, 28),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
                cv2.putText(vis, f"{prov}  ok={ok_flag}", (10, 56),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 220, 0) if ok_flag else (0, 0, 255), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW_NAME, vis)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), 27):  # q או ESC
                break
            elif key == ord(' '):
                paused = not paused

    finally:
        _cleanup()


if __name__ == "__main__":
    main()
