# -------------------------------------------------------
# 🖥️ ProCoach — מצלמה + דשבורד + זיהוי אובייקטים
# תואם ענן (Gunicorn/App Runner) וגם ריצה מקומית (Tk + Flask פנימי)
# -------------------------------------------------------

from __future__ import annotations
import sys, pathlib, os, time, math, threading
from typing import Optional, Dict, Any, List, Tuple

# --- Bootstrap: הרצה ישירה מהשורש או מתיקיית app ---
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]  # BodyPlus_XPro
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

# =============== <<< PATH FIXER (עובד גם מקומית וגם בענן) ===============
# ממפה נתיבי Windows מוחלטים ישנים אל שורש הפרויקט הנוכחי,
# ומנסה אוטומטית נתיב מתוקן כשפותחים קבצים/בודקים קיום.
import builtins, functools

_LEGACY_BASES = [
    r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro",
    r"C:/Users/Owner/Desktop/BodyPlus/BodyPlus_XPro",
]

def _map_legacy_path(p) -> str:
    if p is None:
        return p
    s = str(p)
    s_norm = s.replace("\\\\", "\\").replace("\\", "/")
    for base in _LEGACY_BASES:
        b = base.replace("\\\\", "\\").replace("\\", "/").rstrip("/")
        if s_norm.lower().startswith(b.lower()):
            rel = s_norm[len(b):].lstrip("/")
            fixed = (_PROJECT_ROOT / rel).as_posix()
            return fixed
    return s

_real_open = builtins.open
@functools.wraps(_real_open)
def _open_patched(file, *args, **kwargs):
    try:
        return _real_open(file, *args, **kwargs)
    except FileNotFoundError:
        mapped = _map_legacy_path(file)
        if mapped and mapped != str(file):
            return _real_open(mapped, *args, **kwargs)
        raise
builtins.open = _open_patched

import os.path as _osp
_exists_real = _osp.exists
def _exists_patched(path):
    if _exists_real(path):
        return True
    mapped = _map_legacy_path(path)
    return _exists_real(mapped)
_osp.exists = _exists_patched

def normalize_path(p: str) -> str:
    """אם p מוחלט תחת בסיס ישן → החזר נתיב יחסי לשורש הפרויקט; אחרת השאר כמו שהוא."""
    s = _map_legacy_path(p)
    try:
        pp = pathlib.Path(s)
        if pp.is_absolute():
            rel = pp.resolve().relative_to(_PROJECT_ROOT)
            return rel.as_posix()
    except Exception:
        pass
    return s

def normalize_inplace(obj):
    """מנרמל מחרוזות נתיב בתוך dict/list (למשל אחרי טעינת YAML)."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str):
                obj[k] = normalize_path(v)
            else:
                normalize_inplace(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = normalize_path(v) if isinstance(v, str) else (normalize_inplace(v) or v)
# =======================================================================

# ---------- לוגים ----------
try:
    from core.logs import setup_logging, logger  # type: ignore
    _LOGS_AVAILABLE = True
except Exception:
    _LOGS_AVAILABLE = False
    class _FallbackLogger:
        def info(self, msg): print(f"[INFO] {msg}")
        def warning(self, msg): print(f"[WARN] {msg}")
        def error(self, msg): print(f"[ERROR] {msg}")
        def debug(self, msg): print(f"[DEBUG] {msg}")
    logger = _FallbackLogger()  # type: ignore

# ---------- Admin UI (Flask) ----------
from admin_web.server import create_app
app = create_app()

# --- Health endpoints (LB expects simple 200) ---
@app.get("/health")
def health():
    return "ok", 200

@app.get("/ping")
def ping():
    return "pong", 200

# נשאיר גם את /healthz למי שצריך תאימות לאחור
try:
    @app.get("/healthz")
    def _healthz():
        return "ok", 200
except Exception:
    pass

# ---------- מקור הווידאו ----------
from app.ui.video import get_streamer

# ---------- מדידות ----------
from core.kinematics import KINEMATICS
from core.mediapipe_runner import MediaPipeRunner

# סכימת payload
from core.payload import ensure_schema

# ---------- /payload bridge ----------
try:
    from admin_web.state import set_payload, set_od_engine  # type: ignore
except Exception:
    def set_payload(_p: Dict[str, Any]) -> None:  # type: ignore
        pass
    def set_od_engine(_e) -> None:  # type: ignore
        pass

# ---------- זיהוי אובייקטים ----------
try:
    from core.object_detection.engine import ObjectDetectionEngine
    _OBJDET_AVAILABLE = True
except Exception as e:
    _OBJDET_AVAILABLE = False
    logger.warning(f"Object Detection unavailable: {e}")
    ObjectDetectionEngine = None  # type: ignore

# ---------- תצורה/ביצועים ----------
MP_MAX_WIDTH     = int(os.getenv("MP_MAX_WIDTH", "640"))
HANDS_EVERY_N    = int(os.getenv("HANDS_EVERY_N", "2"))
LOOP_INTERVAL_MS = int(os.getenv("MAIN_LOOP_MS", "15"))
DEFAULT_MIRROR_X = True

PUSH_PERIOD_MS   = int(os.getenv("PUSH_PERIOD_MS", "200"))
SEND_HTTP_PUSH   = os.getenv("SEND_HTTP_PUSH", "0") == "1"
_PUSH_ERR_STATE  = {"sig": None, "count": 0, "last": 0.0}

# אופציונלי: OpenCV
try:
    import cv2
    _OPENCV_AVAILABLE = True
except Exception:
    cv2 = None  # type: ignore
    _OPENCV_AVAILABLE = False

# אופציונלי: requests
try:
    import requests
    _REQUESTS_AVAILABLE = True
except Exception:
    _REQUESTS_AVAILABLE = False


def _init_logging_safe() -> None:
    if not _LOGS_AVAILABLE:
        logger.info("Using fallback console logger (core.logs not available)")
        return
    try:
        try:
            setup_logging(app_name="BodyPlus_XPro", retention="21 days", compression=None)
        except TypeError:
            try:
                setup_logging(app_name="BodyPlus_XPro")
            except TypeError:
                setup_logging("BodyPlus_XPro")
        logger.info("Logging initialized")
    except Exception as e:
        logger.warning(f"setup_logging failed; continuing with fallback logger | err={e!r}")


def start_admin_ui_server(host: str = "127.0.0.1", port: int = 5000) -> None:
    """ריצה מקומית בלבד — Flask פנימי ב-thread נפרד."""
    def _run():
        local_app = create_app()
        logger.info(f"Admin UI starting on http://{host}:{port}")
        local_app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    threading.Thread(target=_run, daemon=True, name="AdminUI").start()


def _extract_mp_landmarks_norm(results_pose, frame_w: int, frame_h: int) -> Optional[List[Dict[str, float]]]:
    try:
        lm = getattr(getattr(results_pose, "pose_landmarks", None), "landmark", None)
        if not lm:
            return None
        out: List[Dict[str, float]] = []
        for p in lm:
            x = float(getattr(p, "x", 0.0)); y = float(getattr(p, "y", 0.0)); v = float(getattr(p, "visibility", 1.0))
            if frame_w and frame_h and (x > 1.5 or y > 1.5):
                x /= float(frame_w); y /= float(frame_h)
            if not (x == x and y == y):
                continue
            out.append({
                "x": max(0.0, min(1.0, x)),
                "y": max(0.0, min(1.0, y)),
                "visibility": max(0.0, min(1.0, v))
            })
        return out if len(out) >= 17 else None
    except Exception:
        return None


def _sanitize_numbers(obj):
    if isinstance(obj, dict):
        return {k: _sanitize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_numbers(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    return obj


def _ensure_detections_block(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    if "detections" in payload and isinstance(payload["detections"], list):
        return payload
    dets: List[Dict[str, Any]] = []
    objs = ((payload.get("objdet") or {}).get("objects")) if isinstance(payload.get("objdet"), dict) else None
    if isinstance(objs, list):
        for o in objs:
            try:
                if not isinstance(o, dict):
                    continue
                conf = o.get("conf")
                bbox = o.get("bbox")
                bb: List[float] = []
                if isinstance(bbox, dict):
                    x = bbox.get("x", bbox.get("x1")); y = bbox.get("y", bbox.get("y1"))
                    w = bbox.get("w"); h = bbox.get("h")
                    if w is not None and h is not None and x is not None and y is not None:
                        bb = [float(x), float(y), float(x + w), float(y + h)]
                    else:
                        x1 = bbox.get("x1"); y1 = bbox.get("y1"); x2 = bbox.get("x2"); y2 = bbox.get("y2")
                        if None not in (x1, y1, x2, y2):
                            bb = [float(x1), float(y1), float(x2), float(y2)]
                elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, a, b = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                    if a > 0 and b > 0:  # [x,y,w,h]
                        bb = [x1, y1, x1 + a, y1 + b]
                    else:                # [x1,y1,x2,y2]
                        bb = [x1, y1, a, b]
                item: Dict[str, Any] = {}
                if bb and all(isinstance(v, (int, float)) for v in bb):
                    item["bbox"] = [float(v) for v in bb[:4]]
                if isinstance(conf, (int, float)) and math.isfinite(float(conf)):
                    item["conf"] = float(conf)
                if item:
                    dets.append(item)
            except Exception:
                continue
    payload["detections"] = dets if dets else []
    payload.setdefault("frame_id", payload.get("frame_id", 0))
    payload.setdefault("ts", payload.get("ts", time.time()))
    return payload


def _dedup_push_error(name: str, detail: Any) -> None:
    try:
        sig = (name, bool(detail))
        now = time.time()
        if _PUSH_ERR_STATE["sig"] != sig or (now - _PUSH_ERR_STATE["last"] > 5.0):
            cnt = _PUSH_ERR_STATE["count"]
            _PUSH_ERR_STATE.update({"sig": sig, "count": 0, "last": now})
            if name not in ("timeout", "payload_push timeout", "payload_push warning: timeout"):
                msg = f"payload_push warning: {name}"
                if detail is not None:
                    msg += f" | detail={detail!r}"
                if cnt:
                    msg += f" | suppressed={cnt}"
                logger.warning(msg)
        else:
            _PUSH_ERR_STATE["count"] += 1
    except Exception:
        pass


class App:
    def __init__(self, cam_index: int = 0):
        _init_logging_safe()

        # ייבוא דחוי של tkinter כדי לא להתרסק בענן (אין תצוגה שם)
        import tkinter as tk  # type: ignore

        # צמצום רעש לוגים בקונסול
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        logging.getLogger('core.logs').setLevel(logging.WARNING)
        logging.getLogger('core.object_detection').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)

        logger.info("Booting ProCoach App…")

        # Tk כריאקטור בלבד (לא מציירים חלונות)
        self.root = tk.Tk()
        self.root.withdraw()

        self.video = None
        self.dashboard = None

        self.running = False
        self.frozen = False
        self._freeze_now_job = None
        self._frozen_frame = None
        self._last_tick: Optional[float] = None
        import time as _t
        self._time = _t
        self._fps_ema: Optional[float] = None
        self._frame_idx: int = 0

        self.cam_index = cam_index
        self.cap = None  # תאימות API

        self.mpr: Optional[MediaPipeRunner] = None

        self.od_engine = None
        self.od_last_update: float = 0.0
        self.od_period_ms: int = 250

        self._last_push_ms: float = 0.0

        self._payload: Dict[str, Any] = {
            "ts_ms": int(self._time.time() * 1000),
            "view_mode": "unknown",
            "metrics": {},
            "visibility": {},
            "meta": {"fps": 0, "warnings": []}
        }
        self._pl_lock = threading.Lock()

        # אתחול
        self._init_mediapipe_runner()
        self._init_object_detection()

        # הגדרות קצב ל-Streamer
        try:
            s = get_streamer()
            env_stream_fps = os.getenv("STREAM_FPS")
            if env_stream_fps:
                s.set_target_fps(int(env_stream_fps))
            env_dec = os.getenv("STREAM_DECIMATION")
            if env_dec:
                s.set_decimation(int(env_dec))
        except Exception as e:
            logger.warning(f"streamer pacing init skipped: {e}")

        # ריצה מקומית בלבד (בענן Gunicorn משרת את app הגלובלי)
        start_admin_ui_server(host="127.0.0.1", port=5000)
        self.start()

        try:
            if hasattr(self.root, "protocol"):
                self.root.protocol("WM_DELETE_WINDOW", self.quit)
        except Exception:
            pass

    # ---------- payload getters/setters ----------
    def _payload_set(self, data: Dict[str, Any]) -> None:
        with self._pl_lock:
            self._payload = data

    def _payload_get(self) -> Dict[str, Any]:
        with self._pl_lock:
            return dict(self._payload)

    # ---------- MediaPipe ----------
    def _init_mediapipe_runner(self) -> None:
        try:
            self.mpr = MediaPipeRunner(
                enable_pose=True,
                enable_hands=True,
                max_width=MP_MAX_WIDTH,
                hands_every_n=HANDS_EVERY_N,
                pose_model_complexity=0  # מהיר יותר על CPU
            ).start()
            logger.info("MediaPipeRunner initialized (pose+hands)")
        except Exception as e:
            logger.warning(f"MediaPipeRunner init failed: {e}")
            self.mpr = None

    # ---------- Object Detection ----------
    def _init_object_detection(self) -> None:
        if not _OBJDET_AVAILABLE:
            logger.warning("זיהוי אובייקטים לא זמין — רץ בלי OD.")
            return
        try:
            yaml_path = normalize_path("core/object_detection/object_detection.yaml")
            self.od_engine = ObjectDetectionEngine.from_yaml(yaml_path)

            try:
                det_cfg = getattr(self.od_engine, "detector_cfg", None)
                if isinstance(det_cfg, dict):
                    normalize_inplace(det_cfg)
            except Exception:
                pass

            per = getattr(getattr(self.od_engine, "detector_cfg", object()), "period_ms", 250)
            self.od_period_ms = max(200, int(per))

            self.od_engine.start()
            logger.info(f"מנוע זיהוי אובייקטים הופעל (period={self.od_period_ms}ms)")

            try:
                set_od_engine(self.od_engine)
                logger.info("OD engine registered to admin_web.state")
            except Exception as e:
                logger.warning(f"failed to register OD engine to state: {e}")

        except Exception as e:
            logger.error(f"שגיאה באתחול זיהוי אובייקטים: {e}")
            self.od_engine = None

    # ---------- לולאה ראשית ----------
    def start(self) -> None:
        self.running = True
        self._last_tick = self._time.time()
        self._fps_ema = None
        logger.info("Main loop started")
        self._loop_once()

    def quit(self) -> None:
        logger.info("Shutting down…")
        self.running = False

        if self.mpr is not None:
            try: self.mpr.release()
            except Exception: pass

        if self.od_engine:
            try: self.od_engine.stop()
            except Exception as e:
                logger.warning(f"שגיאה בסגירת מנוע זיהוי אובייקטים: {e}")

        try:
            self.root.quit(); self.root.destroy()
        except Exception:
            pass

    def _loop_once(self) -> None:
        if not self.running:
            return

        # ---- פריים מה-Streamer ----
        frame = None
        try:
            s = get_streamer()
            ok, frm = s.read_frame()
            if ok and frm is not None and (frm.size > 1):
                frame = frm
        except Exception:
            frame = None

        if frame is None:
            import tkinter as tk  # מקומי
            self.root.after(LOOP_INTERVAL_MS, self._loop_once)
            return

        # ---- MediaPipe ----
        results_pose = None
        results_hands = None
        if self.mpr is not None:
            try:
                proc = frame
                if MP_MAX_WIDTH and _OPENCV_AVAILABLE and frame.shape[1] > MP_MAX_WIDTH:
                    scale = MP_MAX_WIDTH / frame.shape[1]
                    proc = cv2.resize(frame, (MP_MAX_WIDTH, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
                results_pose, results_hands = self.mpr.process(proc)
            except Exception as e:
                logger.warning(f"MediaPipeRunner process failed: {e}")

        # ---- KINEMATICS ----
        image_shape: Tuple[int,int] = (frame.shape[0], frame.shape[1])
        try:
            payload: Dict[str, Any] = KINEMATICS.compute(image_shape, results_pose, results_hands)
        except Exception as e:
            payload = {
                "ts_ms": int(time.time() * 1000),
                "view_mode": "error",
                "metrics": {},
                "visibility": {},
                "meta": {"fps": 0, "warnings": [str(e)]}
            }

        # ---- זיהוי אובייקטים ----
        objdet_payload = self._process_object_detection(frame)
        if objdet_payload:
            payload["objdet"] = objdet_payload

        # ---- mp.landmarks מנורמל ----
        try:
            h, w = image_shape
            mp_lm = _extract_mp_landmarks_norm(results_pose, frame_w=w, frame_h=h)
            if mp_lm:
                mp_block = payload.get("mp", {}) if isinstance(payload.get("mp"), dict) else {}
                mp_block.update({"landmarks": mp_lm, "mirror_x": DEFAULT_MIRROR_X})
                payload["mp"] = mp_block
        except Exception:
            pass

        # ---- ✅ סכימה + סניטציה ----
        payload = ensure_schema(payload)
        payload = _ensure_detections_block(payload)
        payload = _sanitize_numbers(payload)
        payload.setdefault("ts_ms", int(time.time() * 1000))

        # ---- דחיפת payload לזיכרון ----
        self._payload_set(payload)
        try:
            set_payload(payload)
        except Exception:
            pass

        # >>> שליחת HTTP (אופציונלי)
        now_ms = time.time() * 1000.0
        if SEND_HTTP_PUSH and _REQUESTS_AVAILABLE and (now_ms - self._last_push_ms >= PUSH_PERIOD_MS):
            self._last_push_ms = now_ms
            try:
                requests.post("http://127.0.0.1:5000/api/payload_push", json=payload, timeout=0.2)
            except requests.Timeout:
                _dedup_push_error("timeout", None)
            except Exception as e:
                _dedup_push_error("post_failed", str(e))

        import tkinter as tk  # מקומי
        self.root.after(LOOP_INTERVAL_MS, self._loop_once)

    # ---------- OD tick ----------
    def _process_object_detection(self, frame) -> Optional[Dict[str, Any]]:
        if not self.od_engine or frame is None:
            return None
        now_ms = time.time() * 1000
        if (now_ms - self.od_last_update) < self.od_period_ms:
            return None
        self.od_last_update = now_ms
        ts_ms = int(now_ms)
        try:
            self.od_engine.update_frame(frame, ts_ms=ts_ms)
            _tracks, raw_payload = self.od_engine.tick()
            return self._convert_od_payload_for_frontend(raw_payload, frame.shape, ts_ms)
        except Exception as e:
            logger.warning(f"שגיאה בעיבוד זיהוי אובייקטים (ignored): {e}")
            h, w = frame.shape[:2] if hasattr(frame, "shape") else (720, 1280)
            return {
                "frame": {"w": w, "h": h, "mirrored": DEFAULT_MIRROR_X, "ts_ms": ts_ms},
                "objects": [], "tracks": [],
                "detector_state": {"ok": False, "err": str(e), "provider": "unknown", "fps": 0.0}
            }

    def _convert_od_payload_for_frontend(self, raw_payload: Dict[str, Any], frame_shape, ts_ms: int) -> Dict[str, Any]:
        h, w = frame_shape[:2]
        result = {
            "frame": {"w": w, "h": h, "mirrored": DEFAULT_MIRROR_X, "ts_ms": ts_ms},
            "objects": [], "tracks": [],
            "detector_state": {"ok": True, "err": None, "provider": "unknown", "fps": 5.0}
        }
        objects_list = raw_payload.get("objects", [])
        for i, obj in enumerate(objects_list):
            try:
                box = obj.get("box")
                if box and len(box) >= 4:
                    x1, y1, x2, y2 = box[:4]
                    bbox = [int(x1), int(y1), int(x2 - x1), int(y2 - y1)]
                    result["objects"].append({
                        "id": obj.get("track_id", i + 1),
                        "label": obj.get("label", "object"),
                        "bbox": bbox,
                        "conf": obj.get("score", 0.0)
                    })
            except Exception:
                pass
        for i, obj in enumerate(objects_list):
            try:
                track_id = obj.get("track_id", i + 1)
                cx = obj.get("cx", 0); cy = obj.get("cy", 0)
                if cx and cy:
                    result["tracks"].append({
                        "id": track_id, "label": obj.get("label", "object"),
                        "pts": [[ts_ms, float(cx), float(cy)]], "hz": 5.0
                    })
            except Exception:
                pass
        det_state = raw_payload.get("detector_state", {})
        result["detector_state"].update({
            "ok": det_state.get("ok", True),
            "err": det_state.get("last_error"),
            "provider": det_state.get("provider", "unknown"),
            "fps": 5.0
        })
        return result


# ---------- MAIN (רק להרצה מקומית) ----------
if __name__ == "__main__":
    cam_index = int(os.getenv("CAMERA_INDEX", "0"))
    _global_app_instance: Optional[App] = None

    app_local_runner = App(cam_index=cam_index)
    _global_app_instance = app_local_runner

    try:
        import signal
        signal.signal(signal.SIGINT, lambda *_: app_local_runner.quit())
    except Exception:
        pass

    try:
        app_local_runner.root.mainloop()
    finally:
        app_local_runner.quit()
