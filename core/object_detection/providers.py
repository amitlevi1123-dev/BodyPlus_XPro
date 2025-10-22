# core/object_detection/providers.py
# =============================================================================
# Providers for BodyPlus XPro object detection
# - DevNullProvider: no detections (או דמו אם extra.devnull_demo=1)
# - SimProvider: תיבה זזה לסימולציה
# - YoloV8Provider: Ultralytics YOLOv8 (.pt)
# - OnnxProvider: YOLOv8 ONNX (כולל 6/7 עמודות)
# =============================================================================
from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple
import os
import time
import math

import numpy as np

try:
    from loguru import logger
except Exception:  # pragma: no cover
    class _L:
        def info(self, *a, **k): print(*a)
        def warning(self, *a, **k): print(*a)
        def error(self, *a, **k): print(*a)
        def debug(self, *a, **k): print(*a)
    logger = _L()  # type: ignore

# ----- חוזים בסיסיים (מובאים ידנית כדי למנוע תלות מעגלית) -----
BBox = Tuple[int, int, int, int]

class DetectionItem:
    def __init__(self, label: str, score: float, box: BBox):
        self.label = str(label)
        self.score = float(score)
        self.box = (int(box[0]), int(box[1]), int(box[2]), int(box[3]))

class ObjectDetectionConfig:
    """מינימום שדות שהפרוביידרים צריכים; בפועל עובר ה־dataclass המלא מה-base."""
    def __init__(self, **kw: Any):
        for k, v in kw.items():
            setattr(self, k, v)

# ----- כלי עזר לוקאליים (כדי לא למשוך מה-base וליצור מעגלי-ייבוא) -----
def _normalize_token(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")

def _merge_label_maps(cfg: ObjectDetectionConfig) -> Dict[str, str]:
    merged = dict(getattr(cfg, "label_map", {}) or {})
    try:
        extra_map = dict((getattr(cfg, "extra", {}) or {}).get("label_map", {}) or {})
        merged.update(extra_map)
    except Exception:
        pass
    normalized: Dict[str, str] = {}
    for k, v in merged.items():
        if isinstance(k, str) and isinstance(v, str):
            normalized[_normalize_token(k)] = _normalize_token(v)
    return normalized

def _normalize_label(label: str, cfg: ObjectDetectionConfig) -> str:
    t = _normalize_token(label)
    mp = _merge_label_maps(cfg)
    if t in mp:
        return mp[t]
    allowed = {_normalize_token(x) for x in (getattr(cfg, "allowed_labels", []) or [])}
    if allowed and t in allowed:
        return t
    return t

def bgr_to_rgb(arr: np.ndarray) -> np.ndarray:
    return arr[..., ::-1]

# ----- DevNull / Sim ---------------------------------------------------------
class DevNullProvider:
    name = "devnull"
    def __init__(self, cfg: ObjectDetectionConfig):
        extra = (getattr(cfg, "extra", {}) or {})
        self._demo = bool(extra.get("devnull_demo", False))
        self._label = str(extra.get("devnull_label", "barbell"))

    def detect(self, frame_bgr: np.ndarray, threshold: float, overlap: float, max_objects: int, timeout_ms: int):
        if not self._demo:
            return []
        h, w = frame_bgr.shape[:2]
        cx, cy = w // 2, h // 2
        bw, bh = max(60, w // 6), max(60, h // 6)
        x1, y1 = cx - bw // 2, cy - bh // 2
        x2, y2 = x1 + bw, y1 + bh
        return [DetectionItem(label=self._label, score=0.9, box=(x1, y1, x2, y2))]

class SimProvider:
    """תיבת דמו נעה — לבדיקת הצנרת בלי מודל."""
    name = "sim"
    def __init__(self, cfg: ObjectDetectionConfig):
        self._t0 = time.time()
        extra = (getattr(cfg, "extra", {}) or {})
        self._label = str(extra.get("sim_label", "dumbbell"))

    def detect(self, frame_bgr: np.ndarray, threshold: float, overlap: float, max_objects: int, timeout_ms: int):
        h, w = frame_bgr.shape[:2]
        t = time.time() - self._t0
        cx = int((w * 0.5) + (w * 0.2) * math.sin(t))
        cy = int((h * 0.5) + (h * 0.2) * math.cos(1.25 * t))
        bw, bh = int(w * 0.18), int(h * 0.24)
        x1, y1 = max(0, cx - bw // 2), max(0, cy - bh // 2)
        x2, y2 = min(w - 1, x1 + bw), min(h - 1, y1 + bh)
        return [DetectionItem(label=self._label, score=0.95, box=(x1, y1, x2, y2))]

# ----- YOLOv8 (Ultralytics) --------------------------------------------------
class YoloV8Provider:
    name = "yolov8"
    def __init__(self, cfg: ObjectDetectionConfig):
        try:
            from ultralytics import YOLO  # type: ignore
        except Exception as e:
            raise RuntimeError(f"ultralytics not installed: {e}")
        self._device = getattr(cfg, "device", None) or "cpu"
        weights = getattr(cfg, "weights", None) or getattr(cfg, "local_model", None) or "yolov8n.pt"
        self._model = YOLO(weights)
        try:
            self._imgsz = int((getattr(cfg, "extra", {}) or {}).get("imgsz", 640))
        except Exception:
            self._imgsz = 640
        extra = (getattr(cfg, "extra", {}) or {})
        self._allow_any_label = bool(extra.get("allow_any_label", False))
        self._cfg = cfg

    def set_imgsz(self, imgsz: int) -> None:
        if isinstance(imgsz, int) and imgsz > 0:
            self._imgsz = int(imgsz)

    def detect(self, frame_bgr: np.ndarray, threshold: float, overlap: float, max_objects: int, timeout_ms: int):
        frame_rgb = bgr_to_rgb(frame_bgr)
        results = self._model.predict(
            frame_rgb,
            conf=float(threshold),
            iou=float(overlap),
            max_det=int(max_objects),
            verbose=False,
            device=self._device,
            imgsz=self._imgsz,
        )[0]
        names = results.names or {}
        outs: List[DetectionItem] = []
        for b in results.boxes:
            try:
                conf = float(b.conf.item())
                if conf < float(threshold):
                    continue
                cls = int(b.cls.item())
                x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
                raw = str(names.get(cls, cls))
                label = _normalize_label(raw, self._cfg)
                outs.append(DetectionItem(label=label, score=conf, box=(x1, y1, x2, y2)))
            except Exception:
                continue

        if not self._allow_any_label and (getattr(self._cfg, "allowed_labels", []) or []):
            allowed_norm = {_normalize_token(x) for x in self._cfg.allowed_labels}
            outs = [d for d in outs if _normalize_token(d.label) in allowed_norm]

        outs.sort(key=lambda d: d.score, reverse=True)
        return outs[: int(max_objects)]

# ----- ONNX (YOLOv8) ---------------------------------------------------------
def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))

def _letterbox(im: np.ndarray, new_shape=(640, 640), color=(114, 114, 114), stride=32):
    import cv2  # local import to avoid hard dependency if not used
    h0, w0 = im.shape[:2]
    r = min(new_shape[0] / h0, new_shape[1] / w0)
    new_unpad = (int(round(w0 * r)), int(round(h0 * r)))
    dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
    dw /= 2.0; dh /= 2.0
    im = cv2.resize(im, new_unpad, interpolation=cv2.INTER_LINEAR)
    top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
    left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return im, r, (left, top)

def _xywh2xyxy(x: np.ndarray) -> np.ndarray:
    y = x.copy()
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y

def _nms(boxes: np.ndarray, scores: np.ndarray, iou_th: float = 0.45, top_k: int = 300) -> np.ndarray:
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size > 0 and len(keep) < top_k:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        inds = np.where(ovr <= iou_th)[0]
        order = order[inds + 1]
    return np.array(keep, dtype=int)

def _scale_coords_letterbox(boxes: np.ndarray, orig_hw, new_hw, ratio: float, pad) -> np.ndarray:
    (h0, w0) = orig_hw
    (dw, dh) = pad  # left, top from _letterbox
    boxes = boxes.copy()
    boxes[:, [0, 2]] -= dw
    boxes[:, [1, 3]] -= dh
    boxes[:, :4] /= max(ratio, 1e-9)
    boxes[:, 0::2] = boxes[:, 0::2].clip(0, w0 - 1)
    boxes[:, 1::2] = boxes[:, 1::2].clip(0, h0 - 1)
    return boxes

def _standardize_yolov8_output(pred) -> np.ndarray:
    p = np.array(pred)
    if p.ndim == 3 and p.shape[0] == 1:
        p = p[0]
    if p.ndim == 2 and (p.shape[0] in (84, 85, 6, 7)):
        p = p.T
    if p.ndim == 3:
        for ax in range(3):
            if p.shape[ax] in (84, 85, 6, 7):
                order = [i for i in range(3) if i != ax] + [ax]
                q = np.transpose(p, order).reshape(-1, p.shape[ax])
                p = q
                break
    if p.ndim != 2 or p.shape[1] < 6:
        return np.zeros((0, 0), dtype=np.float32)
    return p

class OnnxProvider:
    name = "onnx"
    def __init__(self, cfg: ObjectDetectionConfig):
        try:
            import onnxruntime as ort  # type: ignore
        except Exception as e:
            raise RuntimeError(f"onnxruntime not installed: {e}")
        self._cfg = cfg
        path = getattr(cfg, "onnx_path", None) or getattr(cfg, "weights", None)
        if not path or not os.path.exists(path):
            raise FileNotFoundError(f"ONNX model not found at: {path}")
        self._session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        inp = self._session.get_inputs()[0]
        self._inp_name = inp.name
        ishape = inp.shape
        # נסיון להסיק גודל קלט; אם דינמי—ניעזר ב-extra.imgsz (ברירת מחדל 416)
        try:
            self._ih = int(ishape[2]) if isinstance(ishape[2], int) else int((getattr(cfg, "extra", {}) or {}).get("imgsz", 416) or 416)
            self._iw = int(ishape[3]) if isinstance(ishape[3], int) else int((getattr(cfg, "extra", {}) or {}).get("imgsz", 416) or 416)
        except Exception:
            self._ih = self._iw = int((getattr(cfg, "extra", {}) or {}).get("imgsz", 416) or 416)
        try:
            override = int((getattr(cfg, "extra", {}) or {}).get("imgsz", 0))
            if override > 0:
                self._ih = self._iw = override
        except Exception:
            pass
        # class names (optional)
        self._class_names: Optional[List[str]] = None
        cn = (getattr(cfg, "extra", {}) or {}).get("class_names")
        if isinstance(cn, list):
            self._class_names = [str(x) for x in cn]
        elif isinstance(cn, dict) and cn:
            max_k = max(map(int, cn.keys()))
            self._class_names = [cn.get(str(i), str(i)) for i in range(max_k + 1)]
        extra = (getattr(cfg, "extra", {}) or {})
        self._allow_any = bool(extra.get("allow_any_label", False))
        self._save_dump = bool(int(extra.get("debug_dump", 0)))

    def set_imgsz(self, imgsz: int) -> None:
        if isinstance(imgsz, int) and imgsz > 0:
            self._ih = self._iw = int(imgsz)

    def detect(self, frame_bgr: np.ndarray, threshold: float, overlap: float, max_objects: int, timeout_ms: int):
        img, ratio, (dw, dh) = _letterbox(frame_bgr, (self._ih, self._iw))
        img = bgr_to_rgb(img).astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))[None, ...]  # [1,3,H,W]

        t0 = time.time()
        pred_all = self._session.run(None, {self._inp_name: img})
        pred = pred_all[0]
        infer_ms = (time.time() - t0) * 1000.0

        if self._save_dump:
            try:
                os.makedirs("app/_debug", exist_ok=True)
                np.save("app/_debug/onnx_pred.npy", pred)
            except Exception:
                pass

        pred = _standardize_yolov8_output(pred)
        if pred.size == 0:
            logger.debug("[ONNX] empty prediction")
            return []

        # שני פורמטים: YOLOv8 מלא (84/85) או 6/7-עמודות
        if pred.shape[1] >= 84:
            boxes = _xywh2xyxy(pred[:, :4])
            obj = pred[:, 4:5]
            cls = pred[:, 5:] if pred.shape[1] > 5 else np.zeros((pred.shape[0], 1), dtype=np.float32)
            scores = obj * cls
            class_ids = np.argmax(scores, axis=1)
            confs = scores.max(axis=1)
        elif pred.shape[1] in (6, 7):
            boxes = _xywh2xyxy(pred[:, :4])
            col5 = pred[:, 4].astype(np.float32)
            col6 = pred[:, 5].astype(np.float32) if pred.shape[1] >= 6 else None
            score_raw, cid_raw = col5, col6
            # אם col5 נראה כמו class ids — מחליפים בין העמודות
            def _looks_like_class_ids(v: np.ndarray) -> bool:
                u = np.unique(np.clip(np.round(v), 0, 10**7).astype(int))
                return len(u) <= 10
            if _looks_like_class_ids(col5) and col6 is not None:
                score_raw, cid_raw = col6, col5
            confs = score_raw
            if (np.nanmax(confs) > 1.0) or (np.nanmin(confs) < 0.0):
                confs = _sigmoid(confs)
            class_ids = np.clip(
                np.round(cid_raw).astype(int) if cid_raw is not None else np.zeros((pred.shape[0],), dtype=int),
                0, 10**7
            )
        else:
            return []

        # סינון לפי threshold + NMS
        keep = confs >= float(threshold)
        boxes, confs, class_ids = boxes[keep], confs[keep], class_ids[keep]
        if boxes.size == 0:
            return []

        keep_idx = _nms(boxes, confs, iou_th=float(overlap), top_k=int(max_objects) * 3)
        boxes, confs, class_ids = boxes[keep_idx], confs[keep_idx], class_ids[keep_idx]
        boxes = _scale_coords_letterbox(boxes, frame_bgr.shape[:2], (self._ih, self._iw), float(ratio), (dw, dh))

        outs: List[DetectionItem] = []
        allowed_norm = {_normalize_token(x) for x in (getattr(self._cfg, "allowed_labels", []) or [])}
        for (x1, y1, x2, y2), sc, cid in zip(boxes, confs, class_ids):
            if self._class_names and 0 <= int(cid) < len(self._class_names):
                raw = self._class_names[int(cid)]
            else:
                raw = str(int(cid))
            label = _normalize_label(raw, self._cfg)
            if not self._allow_any and allowed_norm:
                if _normalize_token(label) not in allowed_norm:
                    continue
            outs.append(
                DetectionItem(label=label, score=float(sc),
                              box=(int(x1), int(y1), int(x2), int(y2)))
            )
        outs.sort(key=lambda d: d.score, reverse=True)
        logger.info("[ONNX] infer_ms={:.1f} final={}", infer_ms, len(outs))
        return outs[: int(max_objects)]

__all__ = ["DevNullProvider", "SimProvider", "YoloV8Provider", "OnnxProvider"]
