# -*- coding: utf-8 -*-
"""
routes_objdet.py — Object Detection API routes
------------------------------------------------
כל ה-endpoints הקשורים לזיהוי אובייקטים (YOLO).
כולל worker אופציונלי שעובד עם VideoManager.
"""

from __future__ import annotations
import os
import time
import threading
import logging
from typing import Dict, List, Tuple, Any, Optional
from flask import Blueprint, jsonify, request

try:
    from core.logs import logger
except Exception:
    logger = logging.getLogger("routes_objdet")

from admin_web.video_manager import get_video_manager

# ===== Imports אופציונליים =====
try:
    from ultralytics import YOLO
    _ULTRA_OK = True
except Exception:
    YOLO = None
    _ULTRA_OK = False

try:
    import yaml
    _YAML_OK = True
except Exception:
    yaml = None
    _YAML_OK = False

# ===== State מה-main.py (אם קיים) =====
try:
    from admin_web.state import get_od_engine
except Exception:
    def get_od_engine():
        return None

# ===== Blueprint =====
objdet_bp = Blueprint("objdet", __name__)

# ===== Configuration =====
ENABLE_LOCAL_YOLO_WORKER = os.getenv("ENABLE_LOCAL_YOLO_WORKER", "0") == "1"
OBJDET_YAML = os.getenv(
    "OD_YAML",
    r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro\core\object_detection\object_detection.yaml"
)
OBJDET_PROFILE = os.getenv("DETECTOR_PROFILE", os.getenv("OBJDET_PROFILE", "yolov8_cpu_640"))
OBJDET_CONF = float(os.getenv("OBJDET_CONF", "-1"))
OBJDET_IOU = float(os.getenv("OBJDET_IOU", "-1"))
OBJDET_IMGSZ = int(os.getenv("OBJDET_IMGSZ", "0"))
OBJDET_PERIOD_MS = int(os.getenv("OBJDET_PERIOD_MS", "150"))

# ===== Worker State =====
OBJDET_STATUS_LOCK = threading.Lock()
OBJDET_STATUS: Dict[str, Any] = {
    "running": False,
    "error": "",
    "provider": "yolov8",
    "weights": "",
    "device": "cpu",
    "imgsz": 640,
    "conf": 0.15,
    "iou": 0.50,
    "source": "",
    "fps": 0.0,
}

_OBJDET_WORKER_THREAD: Optional[threading.Thread] = None
_OBJDET_WORKER_STOP = threading.Event()

# ===== Payload Storage (למצב worker מקומי) =====
LAST_PAYLOAD_LOCK = threading.Lock()
LAST_PAYLOAD: Optional[Dict[str, Any]] = None

# ===== Helpers =====
_PRESET2IMGSZ = {"320p": 320, "384p": 384, "416p": 416, "480p": 480, "640p": 640}


def _imgsz_to_preset(v: Optional[int]) -> Optional[str]:
    """ממיר imgsz למחרוזת preset"""
    if v is None:
        return None
    try:
        v = int(v)
    except Exception:
        return None
    return min(_PRESET2IMGSZ.items(), key=lambda kv: abs(kv[1] - v))[0]


def _load_cfg(yml_path: str, profile: str | None) -> Dict[str, Any]:
    """טוען הגדרות מתוך YAML"""
    if not (_YAML_OK and yml_path and os.path.exists(yml_path)):
        return {
            "weights": "core/object_detection/models/best.pt",
            "imgsz": 640,
            "conf": 0.15,
            "iou": 0.50,
            "device": "cpu",
            "classes": ["barbell", "dumbbell"]
        }

    with open(yml_path, "rb") as fb:
        data_bytes = fb.read()

    try:
        text = data_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = data_bytes.decode("utf-8", errors="ignore")
        text = "".join(ch for ch in text if ch.isprintable() or ch in "\r\n\t ")

    data = yaml.safe_load(text) or {}
    prof = profile or data.get("active_profile")
    det = (data.get("profiles", {}).get(prof, {}) or {}).get("detector", {}) if prof else {}
    base = os.path.dirname(os.path.abspath(yml_path))

    def fix(p: Optional[str]) -> Optional[str]:
        if not p:
            return None
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))

    return {
        "weights": fix(det.get("weights_path") or det.get("weights") or "core/object_detection/models/best.pt"),
        "imgsz": int(det.get("imgsz", 640) or 640),
        "conf": float(det.get("threshold", 0.15) or 0.15),
        "iou": float(det.get("overlap", 0.50) or 0.50),
        "device": det.get("device", "cpu") or "cpu",
        "classes": data.get("classes") or ["barbell", "dumbbell"],
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_payload(frame, dets: List[Tuple[int, int, int, int, float, int]], model_names, clslist):
    """ממיר תוצאות YOLO ל-payload"""
    import numpy as np
    if frame is None or not isinstance(frame, np.ndarray):
        h, w = 720, 1280
    else:
        h, w = frame.shape[:2]

    objects = []
    for (x1, y1, x2, y2, conf, cls_id) in dets:
        label = model_names.get(cls_id, str(cls_id)) if isinstance(model_names, dict) else str(cls_id)
        if isinstance(clslist, (list, tuple)) and 0 <= cls_id < len(clslist):
            label = clslist[cls_id]
        objects.append({
            "label": label,
            "conf": float(conf),
            "bbox": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
        })

    return {
        "frame": {"w": w, "h": h, "mirrored": False, "ts_ms": _now_ms()},
        "mp": {"landmarks": []},
        "metrics": {},
        "objdet": {
            "frame": {"w": w, "h": h, "mirrored": False, "ts_ms": _now_ms()},
            "objects": objects,
            "tracks": [],
            "detector_state": {"ok": True, "err": "", "provider": "yolov8", "fps": 0.0},
        },
        "ts": time.time(),
    }


# ===== Worker (רץ רק אם מופעל ידנית) =====
def _objdet_worker():
    """
    Worker של YOLO שמקבל frames מ-VideoManager.
    לא פותח מצלמה בעצמו!
    """
    with OBJDET_STATUS_LOCK:
        OBJDET_STATUS.update({"running": False, "error": ""})

    if not _ULTRA_OK:
        with OBJDET_STATUS_LOCK:
            OBJDET_STATUS.update({"error": "ultralytics_not_installed"})
        logger.error("[ObjDet Worker] Ultralytics not installed")
        return

    cfg = _load_cfg(OBJDET_YAML, OBJDET_PROFILE or None)
    weights = cfg["weights"]
    imgsz = OBJDET_IMGSZ or cfg["imgsz"]
    conf = OBJDET_CONF if OBJDET_CONF >= 0 else cfg["conf"]
    iou = OBJDET_IOU if OBJDET_IOU >= 0 else cfg["iou"]
    device = cfg["device"]
    clslist = cfg["classes"]

    if not weights or not os.path.exists(weights):
        msg = f"weights_not_found: {weights}"
        with OBJDET_STATUS_LOCK:
            OBJDET_STATUS.update({"error": msg})
        logger.error(f"[ObjDet Worker] {msg}")
        return

    model = YOLO(weights).to(device)
    with OBJDET_STATUS_LOCK:
        OBJDET_STATUS.update({
            "running": True,
            "error": "",
            "weights": weights,
            "device": device,
            "imgsz": imgsz,
            "conf": conf,
            "iou": iou,
            "source": "VideoManager"
        })
    logger.info(f"[ObjDet Worker] YOLO loaded | weights={weights} | device={device} | imgsz={imgsz}")

    vm = get_video_manager()
    period_ms = max(60, OBJDET_PERIOD_MS)
    frames_processed = 0

    while not _OBJDET_WORKER_STOP.is_set():
        # קבלת פריים מה-VideoManager (לא פותחים מצלמה!)
        if not vm.is_ready():
            time.sleep(0.1)
            continue

        frame = vm.get_frame()
        if frame is None:
            time.sleep(0.01)
            continue

        t0 = time.time()

        # הרצת YOLO
        try:
            res = model.predict(source=frame, imgsz=imgsz, conf=conf, iou=iou, device=device, verbose=False)[0]
        except Exception as e:
            logger.warning(f"[ObjDet Worker] YOLO predict failed: {e}")
            time.sleep(0.1)
            continue

        dets: List[Tuple[int, int, int, int, float, int]] = []
        if res.boxes is not None and len(res.boxes) > 0:
            xyxy = res.boxes.xyxy.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy()
            clss = res.boxes.cls.cpu().numpy().astype(int)
            for (x1, y1, x2, y2), c, cl in zip(xyxy, confs, clss):
                dets.append((int(x1), int(y1), int(x2), int(y2), float(c), int(cl)))

        payload = _to_payload(frame, dets, getattr(model, "names", {}), clslist)

        # שמירת payload
        with LAST_PAYLOAD_LOCK:
            globals()["LAST_PAYLOAD"] = payload

        frames_processed += 1
        elapsed_ms = (time.time() - t0) * 1000.0
        fps = 1000.0 / max(1.0, elapsed_ms)

        with OBJDET_STATUS_LOCK:
            OBJDET_STATUS["fps"] = round(fps, 2)

        sleep_ms = max(0.0, period_ms - elapsed_ms)
        time.sleep(sleep_ms / 1000.0)

    with OBJDET_STATUS_LOCK:
        OBJDET_STATUS.update({"running": False, "error": "stopped"})

    logger.info(f"[ObjDet Worker] Stopped (processed {frames_processed} frames)")


# =================== API Routes ===================

@objdet_bp.route("/api/objdet/status", methods=["GET"])
def objdet_status():
    """
    מחזיר סטטוס של מנוע ה-OD.
    מעדיף את המנוע החי (מה-main.py), אחרת את ה-worker המקומי.
    """
    eng = get_od_engine()
    if eng is not None:
        try:
            rp = eng.get_runtime_params()
            out = {
                "running": True,
                "error": "",
                "provider": rp.get("profile") or rp.get("provider") or "unknown",
                "device": rp.get("device", "cpu"),
                "imgsz": _PRESET2IMGSZ.get(
                    str(rp.get("input_size") or ""),
                    getattr(getattr(eng, "detector_cfg", object()), "extra", {}).get("imgsz", 640)
                ),
                "conf": float(rp.get("confidence_threshold", 0.15)),
                "iou": float(rp.get("overlap", 0.50)),
                "source": "",
                "fps": 0.0,
                "enabled_by_env": True,
                "yaml": os.getenv("OD_YAML", OBJDET_YAML),
            }
            return jsonify(out), 200
        except Exception as e:
            logger.warning(f"/api/objdet/status (engine) failed: {e}")

    # fallback: worker מקומי
    with OBJDET_STATUS_LOCK:
        st = dict(OBJDET_STATUS)
    st["enabled_by_env"] = ENABLE_LOCAL_YOLO_WORKER
    st["yaml"] = OBJDET_YAML
    return jsonify(st), 200


@objdet_bp.route("/api/objdet/config", methods=["GET"])
def api_objdet_config_get():
    """מחזיר קונפיג נוכחי של OD"""
    eng = get_od_engine()
    if eng is not None:
        try:
            snap = eng.get_simple()
            thr = float(snap.get("confidence_threshold", 0.15))
            iou = float(snap.get("overlap", 0.50))
            maxo = int(snap.get("max_objects", 50))
            period = int(snap.get("detection_rate_ms", 150))
            preset = snap.get("input_size")
            imgsz = _PRESET2IMGSZ.get(preset, getattr(getattr(eng, "detector_cfg", object()), "extra", {}).get("imgsz", 640))
            out = {
                "threshold": thr,
                "overlap": iou,
                "max_objects": maxo,
                "imgsz": int(imgsz),
                "period_ms": period,
                "profile": getattr(eng.detector_cfg, "provider", "unknown"),
                "device": getattr(eng.detector_cfg, "device", "cpu"),
                "weights": getattr(eng.detector_cfg, "weights", "") or getattr(eng.detector_cfg, "local_model", ""),
            }
            return jsonify(out), 200
        except Exception as e:
            logger.warning(f"/api/objdet/config GET (engine) failed: {e}")

    # fallback
    return api_od_config_get()


@objdet_bp.route("/api/objdet/config", methods=["POST"])
def api_objdet_config_post():
    """מעדכן קונפיג של OD"""
    try:
        body = request.get_json(force=True, silent=False) or {}
    except Exception:
        return jsonify(ok=False, error="bad_json"), 400

    eng = get_od_engine()
    if eng is not None:
        patch = {}
        if "threshold" in body:
            patch["confidence_threshold"] = float(body["threshold"])
        if "overlap" in body:
            patch["overlap"] = float(body["overlap"])
        if "max_objects" in body:
            patch["max_objects"] = int(body["max_objects"])
        if "period_ms" in body:
            patch["detection_rate_ms"] = int(body["period_ms"])
        if "imgsz" in body:
            preset = _imgsz_to_preset(int(body["imgsz"]))
            if preset:
                patch["input_size"] = preset
        if "tracking_enabled" in body:
            patch["tracking_enabled"] = bool(body["tracking_enabled"])
        if isinstance(body.get("allowed_labels"), list):
            patch["allowed_labels"] = [str(x) for x in body["allowed_labels"]]

        try:
            snap = eng.update_simple(patch)
            return jsonify(ok=True, applied=True, snapshot=snap), 200
        except Exception as e:
            logger.exception("/api/objdet/config POST failed (engine)")
            return jsonify(ok=False, error=str(e)), 500

    # fallback
    return api_od_config_post()


@objdet_bp.route("/api/objdet/start", methods=["POST"])
def objdet_start():
    """
    מתחיל את ה-worker המקומי של YOLO.
    דורש שהמצלמה תהיה פתוחה (דרך VideoManager).
    """
    if not ENABLE_LOCAL_YOLO_WORKER:
        return jsonify(ok=False, error="local_worker_disabled_by_default"), 400

    vm = get_video_manager()
    if not vm.is_ready():
        return jsonify(ok=False, error="video_not_started", hint="Start video first via /api/video/start"), 400

    with OBJDET_STATUS_LOCK:
        if OBJDET_STATUS.get("running"):
            return jsonify(ok=False, error="already_running"), 400

    _OBJDET_WORKER_STOP.clear()

    def runner():
        try:
            _objdet_worker()
        except Exception as e:
            with OBJDET_STATUS_LOCK:
                OBJDET_STATUS.update({"running": False, "error": f"worker_crash: {e}"})
            logger.exception("[ObjDet Worker] crashed")

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    logger.info("[ObjDet Worker] Started via /api/objdet/start")
    return jsonify(ok=True, status="started")


@objdet_bp.route("/api/objdet/stop", methods=["POST"])
def objdet_stop():
    """עוצר את ה-worker המקומי"""
    _OBJDET_WORKER_STOP.set()
    return jsonify(ok=True, status="stopping")


# ===== Legacy Routes (תאימות לאחור) =====

@objdet_bp.route("/api/od/config", methods=["GET"])
def api_od_config_get():
    """Legacy config GET"""
    try:
        cfg = _load_cfg(OBJDET_YAML, OBJDET_PROFILE or None)
        out = {
            "threshold": float(cfg.get("conf", 0.15)),
            "overlap": float(cfg.get("iou", 0.50)),
            "max_objects": 50,
            "period_ms": int(OBJDET_PERIOD_MS or 150),
            "imgsz": int(cfg.get("imgsz", 640)),
            "weights": cfg.get("weights") or "",
            "device": cfg.get("device") or "cpu",
            "profile": OBJDET_PROFILE,
        }
        return jsonify(out), 200
    except Exception as e:
        logger.exception("api_od_config_get failed")
        return jsonify(error=str(e)), 500


@objdet_bp.route("/api/od/config", methods=["POST"])
def api_od_config_post():
    """Legacy config POST"""
    try:
        body = request.get_json(force=True, silent=False) or {}
        if "threshold" in body:
            os.environ["OBJDET_CONF"] = str(float(body["threshold"]))
            globals()["OBJDET_CONF"] = float(body["threshold"])
        if "overlap" in body:
            os.environ["OBJDET_IOU"] = str(float(body["overlap"]))
            globals()["OBJDET_IOU"] = float(body["overlap"])
        if "imgsz" in body:
            os.environ["OBJDET_IMGSZ"] = str(int(body["imgsz"]))
            globals()["OBJDET_IMGSZ"] = int(body["imgsz"])
        if "period_ms" in body:
            os.environ["OBJDET_PERIOD_MS"] = str(int(body["period_ms"]))
            globals()["OBJDET_PERIOD_MS"] = int(body["period_ms"])

        with OBJDET_STATUS_LOCK:
            running = bool(OBJDET_STATUS.get("running"))

        if running:
            # restart worker
            _OBJDET_WORKER_STOP.set()
            time.sleep(0.2)
            _OBJDET_WORKER_STOP.clear()
            t = threading.Thread(target=_objdet_worker, daemon=True)
            t.start()

        return jsonify(ok=True, applied=True), 200
    except Exception as e:
        logger.exception("api_od_config_post failed")
        return jsonify(ok=False, error=str(e)), 400


# ===== Page Route =====
# הועבר בחזרה ל-server.py לתאימות עם templates קיימים
