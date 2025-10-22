# =============================================================================
# BodyPlus XPro — Detector Service (Base)
# - דאטה־קלאסים, שירות ה-Detector, טרקר קליל, Utilities
# - ה-Providers נטענים דינמית (importlib) למניעת תלות מעגלית ושגיאות IDE
# =============================================================================
from __future__ import annotations
import os
import time
import threading
import importlib
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any

import numpy as np  # frame_bgr: np.ndarray (BGR)

# ---------- Logging ----------
try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def info(self, *a, **k): ...
        def warning(self, *a, **k): ...
        def error(self, *a, **k): ...
        def debug(self, *a, **k): ...
    logger = _NullLogger()  # type: ignore

# ---------- Anti-flood (INFO רק פעם בכמה זמן כאשר יש דיטקציות) ----------
_DET_INFO_LAST_MS = 0
_DET_INFO_COOLDOWN_MS = int(os.getenv("DET_INFO_COOLDOWN_MS", "3000"))  # ברירת מחדל: 3s

# ---------- Data Contracts ----------
BBox = Tuple[int, int, int, int]  # (x1, y1, x2, y2)

@dataclass
class DetectionItem:
    label: str
    score: float
    box: BBox

@dataclass
class DetectorState:
    ok: bool
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None
    last_ts_ms: Optional[int] = None
    provider: Optional[str] = None

@dataclass
class ObjectDetectionConfig:
    enabled: bool = True
    provider: str = "devnull"            # devnull | yolov8 | onnx | sim

    # thresholds & timings
    threshold: float = 0.35
    overlap: float = 0.60
    max_objects: int = 12
    timeout_ms: int = 2500
    period_ms: int = 150
    clip_to_frame: bool = True

    # model paths / device
    weights: Optional[str] = None
    local_model: Optional[str] = None
    device: Optional[str] = None
    onnx_path: Optional[str] = None
    input_size: Optional[List[int]] = None

    # labels
    allowed_labels: List[str] = field(default_factory=list)
    label_map: Dict[str, str] = field(default_factory=lambda: {
        "bar": "barbell", "bar_bell": "barbell", "olympic_bar": "barbell",
        "dumbbells": "dumbbell", "db": "dumbbell", "d-bell": "dumbbell", "weight": "dumbbell",
    })

    # runtime extras
    extra: Dict[str, Any] = field(default_factory=dict)

    # simple.*
    tracking_enabled: bool = False
    safe_mode_enabled: bool = False
    safe_mode_top_k: int = 12
    input_size_preset: Optional[str] = None  # "320p"|"384p"|"416p"|"480p"|"640p"

# ---------- Simple Tracker (built-in) ----------
@dataclass
class Track:
    track_id: int
    label: str
    score: float
    box: BBox
    hits: int = 1
    miss: int = 0

class CentroidTracker:
    """טרקר קליל (IOU/צנטרואיד) לייצוב בסיסי."""
    def __init__(self, max_iou_miss: float = 0.15, max_centroid_px: int = 80, ttl: int = 10):
        self._next_id = 1
        self._tracks: Dict[int, Track] = {}
        self.max_iou_miss = float(max_iou_miss)
        self.max_centroid_px = int(max_centroid_px)
        self.ttl = int(ttl)

    @staticmethod
    def _iou(a: BBox, b: BBox) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        inter_x1 = max(ax1, bx1); inter_y1 = max(ay1, by1)
        inter_x2 = min(ax2, bx2); inter_y2 = min(ay2, by2)
        iw = max(0, inter_x2 - inter_x1); ih = max(0, inter_y2 - inter_y1)
        inter = iw * ih
        if inter <= 0: return 0.0
        area_a = max(1, (ax2 - ax1)) * max(1, (ay2 - ay1))
        area_b = max(1, (bx2 - bx1)) * max(1, (by2 - by1))
        return inter / (area_a + area_b - inter)

    @staticmethod
    def _centroid(b: BBox) -> Tuple[int, int]:
        x1, y1, x2, y2 = b
        return (int((x1 + x2) / 2), int((y1 + y2) / 2))

    @staticmethod
    def _dist2(p: Tuple[int, int], q: Tuple[int, int]) -> float:
        dx, dy = p[0] - q[0], p[1] - q[1]
        return dx * dx + dy * dy

    def update(self, detections: List[DetectionItem]) -> List[Track]:
        logger.debug("[Tracker] update start n_dets={}", len(detections))
        for tr in self._tracks.values():
            tr.miss += 1

        used_det = set()
        for tid, tr in list(self._tracks.items()):
            best_idx = -1
            best_score = -1.0
            tc = self._centroid(tr.box)
            for i, det in enumerate(detections):
                if i in used_det:
                    continue
                iou = self._iou(tr.box, det.box)
                dc = self._centroid(det.box)
                d2 = self._dist2(tc, dc)
                score = iou - (d2 ** 0.5) / max(1.0, float(self.max_centroid_px))
                if score > best_score:
                    best_score = score
                    best_idx = i
            if best_idx >= 0:
                det = detections[best_idx]
                dc = self._centroid(det.box); tc = self._centroid(tr.box)
                if self._iou(tr.box, det.box) >= self.max_iou_miss or ((self._dist2(tc, dc) ** 0.5) <= self.max_centroid_px):
                    tr.box = det.box; tr.label = det.label; tr.score = det.score
                    tr.hits += 1; tr.miss = 0
                    used_det.add(best_idx)

        for i, det in enumerate(detections):
            if i in used_det: continue
            tid = self._next_id; self._next_id += 1
            self._tracks[tid] = Track(track_id=tid, label=det.label, score=det.score, box=det.box)

        for tid in list(self._tracks.keys()):
            if self._tracks[tid].miss > self.ttl:
                del self._tracks[tid]

        out = list(self._tracks.values())
        logger.debug("[Tracker] update end n_tracks={}", len(out))
        return out

# ---------- Utilities ----------
def _clip_box(box: BBox, w: int, h: int) -> Optional[BBox]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(int(x1), w - 1)); y1 = max(0, min(int(y1), h - 1))
    x2 = max(0, min(int(x2), w - 1)); y2 = max(0, min(int(y2), h - 1))
    if x2 <= x1 or y2 <= y1: return None
    return (x1, y1, x2, y2)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _normalize_token(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")

def _merge_label_maps(cfg: ObjectDetectionConfig) -> Dict[str, str]:
    merged = dict(cfg.label_map or {})
    try:
        extra_map = dict((cfg.extra or {}).get("label_map", {}) or {})
        merged.update(extra_map)
    except Exception:
        pass
    normalized = {}
    for k, v in merged.items():
        if isinstance(k, str) and isinstance(v, str):
            normalized[_normalize_token(k)] = _normalize_token(v)
    return normalized

def _normalize_label(label: str, cfg: ObjectDetectionConfig) -> str:
    t = _normalize_token(label)
    mp = _merge_label_maps(cfg)
    if t in mp: return mp[t]
    allowed = {_normalize_token(x) for x in (cfg.allowed_labels or [])}
    if allowed and t in allowed: return t
    return t

def _as_xyxy_clipped(items: List[DetectionItem], w: int, h: int, clip: bool) -> List[DetectionItem]:
    outs: List[DetectionItem] = []
    for it in (items or []):
        box = (int(it.box[0]), int(it.box[1]), int(it.box[2]), int(it.box[3]))
        if clip:
            clipped = _clip_box(box, w, h)
            if clipped is None: continue
            box = clipped
        outs.append(DetectionItem(label=it.label, score=float(it.score), box=box))
    return outs

# =============================================================================
# Detector Service
# =============================================================================
_GLOBAL_CFG: Optional[ObjectDetectionConfig] = None  # לשיתוף עם providers בזמן נרמול לייבלים

class DetectorService:
    """
    API ל-ENGINE:
      - detect(frame_bgr, ts_ms=None) -> List[DetectionItem]
      - state (property) -> DetectorState
      - apply_simple(dict) / update_simple(dict)
      - get_runtime_params() / get_health()
      - get_last_tracks()

    יש גם API אסינכרוני: start/stop/update_frame/get_last_objects
    """

    def __init__(self, cfg: ObjectDetectionConfig):
        global _GLOBAL_CFG
        _GLOBAL_CFG = cfg

        self.cfg = cfg
        self._frame_lock = threading.Lock()
        self._last_frame: Optional[np.ndarray] = None

        self._res_lock = threading.Lock()
        self._last_objects: List[DetectionItem] = []
        self._last_tracks: List[Track] = []
        self._state = DetectorState(ok=True, provider=cfg.provider)

        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None

        self._provider = self._resolve_provider(cfg)
        self._last_run_ms = 0
        self._running_call = False

        # Health metrics
        self._last_detect_ms: Optional[int] = None
        self._avg_latency_ms: float = 0.0
        self._lat_alpha: float = 0.25
        self._fps: float = 0.0
        self._fps_window: List[float] = []

        # Tracker (אופציונלי)
        self._tracker: Optional[CentroidTracker] = CentroidTracker(ttl=10) if cfg.tracking_enabled else None

        # החלה ראשונית של simple.* (מצב פתיחה תואם YAML)
        self.apply_simple({
            "detection_rate_ms": cfg.period_ms,
            "confidence_threshold": cfg.threshold,
            "max_objects": cfg.max_objects,
            "safe_mode": {"enabled": cfg.safe_mode_enabled, "top_k": cfg.safe_mode_top_k},
            "tracking_enabled": cfg.tracking_enabled,
            "allowed_labels": cfg.allowed_labels,
            "input_size": cfg.input_size_preset or self._extract_input_preset_from_extra(cfg.extra),
        })

        logger.info(
            "DetectorService init: provider={} thr={} ov={} max={} imgsz={} track?={}",
            cfg.provider, cfg.threshold, cfg.overlap, cfg.max_objects,
            (cfg.extra or {}).get("imgsz"), cfg.tracking_enabled
        )

    # --------- Engine-facing API ---------
    @property
    def state(self) -> DetectorState:
        with self._res_lock:
            return DetectorState(
                ok=self._state.ok,
                last_latency_ms=self._state.last_latency_ms,
                last_error=self._state.last_error,
                last_ts_ms=self._state.last_ts_ms,
                provider=self._state.provider,
            )

    def detect(self, frame_bgr: np.ndarray, ts_ms: Optional[int] = None) -> List[DetectionItem]:
        if frame_bgr is None:
            logger.warning("[Detector] detect called with empty frame")
            return []

        h, w = frame_bgr.shape[:2]
        t0 = _now_ms()
        logger.debug("[Detector] start w={} h={} thr={} ov={} max={} clip={} safe={}",
                     w, h, self.cfg.threshold, self.cfg.overlap, self.cfg.max_objects,
                     self.cfg.clip_to_frame, self.cfg.safe_mode_enabled)
        try:
            raw = self._provider.detect(
                frame_bgr=frame_bgr,
                threshold=float(self.cfg.threshold),
                overlap=float(self.cfg.overlap),
                max_objects=int(self.cfg.max_objects),
                timeout_ms=int(self.cfg.timeout_ms),
            )
            n_raw = len(raw or [])

            # Normalize/clip
            cleaned = _as_xyxy_clipped(raw or [], w, h, clip=bool(self.cfg.clip_to_frame))
            n_clip = len(cleaned)

            # cap + סדר דטרמיניסטי (score ואז שטח)
            def _area(b: BBox) -> int:
                return max(1, (b[2] - b[0])) * max(1, (b[3] - b[1]))
            cleaned.sort(key=lambda d: (d.score, _area(d.box)), reverse=True)

            # SAFE MODE / MAX
            if self.cfg.safe_mode_enabled:
                k = min(int(self.cfg.safe_mode_top_k), int(self.cfg.max_objects))
                cleaned = cleaned[:k]
            else:
                cleaned = cleaned[: int(self.cfg.max_objects)]
            n_after_cap = len(cleaned)

            # Allowed labels
            allow_any = bool((self.cfg.extra or {}).get("allow_any_label", False))
            if not allow_any and self.cfg.allowed_labels:
                allowed_norm = {_normalize_token(x) for x in self.cfg.allowed_labels}
                cleaned = [d for d in cleaned if _normalize_token(d.label) in allowed_norm]
            n_after_labels = len(cleaned)

            # Tracking (optional)
            tracks: List[Track] = []
            if self._tracker is not None and self.cfg.tracking_enabled:
                tracks = self._tracker.update(cleaned)
                logger.debug("[Detector] tracker updated in_tracks={} out_tracks={}", n_after_labels, len(tracks))

            t1 = _now_ms()
            latency = t1 - t0
            self._update_health(latency)

            with self._res_lock:
                self._last_objects = cleaned
                self._last_tracks = tracks
                self._state = DetectorState(
                    ok=True,
                    last_latency_ms=latency,
                    last_error=None,
                    last_ts_ms=ts_ms if ts_ms is not None else t1,
                    provider=getattr(self._provider, "name", self.cfg.provider),
                )

            # ---------- Anti-flood logging ----------
            global _DET_INFO_LAST_MS
            now_ms = _now_ms()
            should_info = (n_after_labels > 0) and ((now_ms - _DET_INFO_LAST_MS) >= _DET_INFO_COOLDOWN_MS)

            logf = logger.info if should_info else logger.debug
            logf(
                "[Detector] ok provider={} raw={} clipped={} after_cap={} after_labels={} latency={}ms thr={} ov={} max={}",
                getattr(self._provider, 'name', self.cfg.provider),
                n_raw, n_clip, n_after_cap, n_after_labels, latency,
                self.cfg.threshold, self.cfg.overlap, self.cfg.max_objects
            )
            if should_info:
                _DET_INFO_LAST_MS = now_ms
            # ---------------------------------------

            return cleaned

        except Exception as e:
            t1 = _now_ms()
            self._update_health(t1 - t0)
            with self._res_lock:
                self._state = DetectorState(
                    ok=False,
                    last_latency_ms=t1 - t0,
                    last_error=str(e),
                    last_ts_ms=ts_ms if ts_ms is not None else t1,
                    provider=getattr(self._provider, "name", self.cfg.provider),
                )
                self._last_tracks = []
                self._last_objects = []
            logger.error("[Detector] ERROR provider={} err={}", getattr(self._provider, 'name', self.cfg.provider), e)
            return []

    # --------- Optional async API ---------
    def start(self) -> None:
        if not self.cfg.enabled:
            with self._res_lock:
                self._state = DetectorState(ok=False, last_error="disabled", provider=self.cfg.provider)
            logger.warning("DetectorService worker not started (disabled) provider={}", self.cfg.provider)
            return
        if self._worker and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._loop, name="DetectorService", daemon=True)
        self._worker.start()
        logger.info("DetectorService worker started (period={}ms)", self.cfg.period_ms)

    def stop(self) -> None:
        self._stop.set()
        if self._worker:
            self._worker.join(timeout=1.5)
        self._worker = None
        logger.info("DetectorService worker stopped")

    def update_frame(self, frame_bgr: np.ndarray) -> None:
        if frame_bgr is None:
            return
        with self._frame_lock:
            self._last_frame = frame_bgr

    def get_last_objects(self) -> Tuple[List[DetectionItem], DetectorState]:
        with self._res_lock:
            objs = list(self._last_objects)
            state = DetectorState(
                ok=self._state.ok,
                last_latency_ms=self._state.last_latency_ms,
                last_error=self._state.last_error,
                last_ts_ms=self._state.last_ts_ms,
                provider=self._state.provider,
            )
        return objs, state

    def get_last_tracks(self) -> List[Track]:
        with self._res_lock:
            return list(self._last_tracks)

    # --------- Internals ---------
    def _resolve_provider(self, cfg: ObjectDetectionConfig):
        """
        טוען את core.object_detection.providers דינמית ומביא את המחלקה הנדרשת.
        זה מונע תלות מעגלית ומחסל את ה"אדומים" של IDE על import סטטי.
        """
        module_name = (f"{__package__}.providers" if __package__ else "core.object_detection.providers")
        try:
            providers_mod = importlib.import_module(module_name)
        except Exception as e:
            logger.error("Failed importing providers module '{}': {}", module_name, e)
            raise

        name = (cfg.provider or "").lower().strip()
        logger.info("Detector provider resolve: {}", name)

        def _get(cls_name: str):
            try:
                return getattr(providers_mod, cls_name)
            except Exception as e:
                logger.warning("Provider class '{}' not found in {} ({})", cls_name, module_name, e)
                return None

        if name in ("", "devnull"):
            P = _get("DevNullProvider");  return P(cfg) if P else None
        if name in ("sim", "simulate", "simulation"):
            P = _get("SimProvider");      return P(cfg) if P else None
        if name == "yolov8":
            P = _get("YoloV8Provider")
            if P:
                try:
                    return P(cfg)
                except BaseException as e:
                    logger.warning("YOLOv8 provider init failed -> devnull ({})", e)
        if name == "onnx":
            P = _get("OnnxProvider")
            if P:
                try:
                    return P(cfg)
                except BaseException as e:
                    logger.warning("ONNX provider init failed -> devnull ({})", e)

        # Fallback
        P = _get("DevNullProvider")
        return P(cfg) if P else None

    def _loop(self) -> None:
        while not self._stop.is_set():
            period = max(50, int(self.cfg.period_ms))
            now = _now_ms()
            if now - self._last_run_ms < period:
                time.sleep(0.005); continue
            if self._running_call:
                self._last_run_ms = now; continue

            frame = self._get_latest_frame()
            if frame is None:
                time.sleep(0.01)
                self._last_run_ms = now
                continue

            self._running_call = True
            try:
                _ = self.detect(frame_bgr=frame, ts_ms=now)
            finally:
                self._running_call = False
                self._last_run_ms = _now_ms()

    def _get_latest_frame(self) -> Optional[np.ndarray]:
        with self._frame_lock:
            return None if self._last_frame is None else self._last_frame

    # -------------------------
    # Simple Controls Runtime
    # -------------------------
    def _extract_input_preset_from_extra(self, extra: Optional[Dict[str, Any]]) -> Optional[str]:
        try:
            imgsz = int((extra or {}).get("imgsz"))
            if imgsz <= 0: return None
            if imgsz <= 320: return "320p"
            if imgsz <= 384: return "384p"
            if imgsz <= 416: return "416p"
            if imgsz <= 480: return "480p"
            return "640p"
        except Exception:
            return None

    def _imgsz_from_preset(self, preset: Optional[str]) -> Optional[int]:
        if not preset: return None
        preset = str(preset).lower().strip()
        table = {"320p": 320, "384p": 384, "416p": 416, "480p": 480, "640p": 640}
        return table.get(preset)

    def apply_simple(self, simple: Dict[str, Any]) -> None:
        if not isinstance(simple, dict): return
        # period / threshold / max / labels
        if "detection_rate_ms" in simple:
            try: self.cfg.period_ms = int(simple["detection_rate_ms"])
            except Exception: pass
        if "confidence_threshold" in simple:
            try: self.cfg.threshold = float(simple["confidence_threshold"])
            except Exception: pass
        if "max_objects" in simple:
            try: self.cfg.max_objects = int(simple["max_objects"])
            except Exception: pass
        if "allowed_labels" in simple and isinstance(simple["allowed_labels"], list):
            self.cfg.allowed_labels = [str(x) for x in simple["allowed_labels"]]

        # safe mode
        sm = simple.get("safe_mode", {})
        if isinstance(sm, dict):
            if "enabled" in sm:
                self.cfg.safe_mode_enabled = bool(sm["enabled"])
            if "top_k" in sm:
                try: self.cfg.safe_mode_top_k = int(sm["top_k"])
                except Exception: pass

        # tracking
        if "tracking_enabled" in simple:
            self.cfg.tracking_enabled = bool(simple["tracking_enabled"])
            if self.cfg.tracking_enabled and self._tracker is None:
                self._tracker = CentroidTracker(ttl=10)
            if not self.cfg.tracking_enabled:
                self._tracker = None

        # input size (affects YOLO imgsz)
        if "input_size" in simple:
            self.cfg.input_size_preset = str(simple["input_size"])
            imgsz = self._imgsz_from_preset(self.cfg.input_size_preset)
            if imgsz:
                self.cfg.extra["imgsz"] = int(imgsz)
                if hasattr(self._provider, "set_imgsz"):
                    try:
                        self._provider.set_imgsz(int(imgsz))  # type: ignore[attr-defined]
                    except Exception:
                        pass

        logger.info(
            "[Detector.apply_simple] rate_ms={} thr={} max={} safe=({}, {}) tracking={} imgsz={}",
            self.cfg.period_ms, self.cfg.threshold, self.cfg.max_objects,
            self.cfg.safe_mode_enabled, self.cfg.safe_mode_top_k,
            self.cfg.tracking_enabled, (self.cfg.extra or {}).get("imgsz")
        )

    def update_simple(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        self.apply_simple(patch or {})
        snap = {
            "input_size": self.cfg.input_size_preset or self._extract_input_preset_from_extra(self.cfg.extra),
            "detection_rate_ms": self.cfg.period_ms,
            "confidence_threshold": self.cfg.threshold,
            "max_objects": self.cfg.max_objects,
            "safe_mode": {"enabled": self.cfg.safe_mode_enabled, "top_k": self.cfg.safe_mode_top_k},
            "tracking_enabled": self.cfg.tracking_enabled,
            "allowed_labels": list(self.cfg.allowed_labels or []),
        }
        logger.info("[Detector.update_simple] {}", snap)
        return snap

    # -------------------------
    # Health / Wiring helpers
    # -------------------------
    def _update_health(self, latency_ms: int):
        now_ms = int(time.time() * 1000)
        # FPS
        if self._last_detect_ms is not None:
            dt = (now_ms - self._last_detect_ms) / 1000.0
            if dt > 0:
                self._fps_window.append(dt)
                if len(self._fps_window) > 20:
                    self._fps_window.pop(0)
                avg_dt = sum(self._fps_window) / max(1, len(self._fps_window))
                self._fps = 1.0 / avg_dt if avg_dt > 0 else 0.0
        self._last_detect_ms = now_ms
        # latency EMA
        self._avg_latency_ms = (
            latency_ms if self._avg_latency_ms == 0.0
            else 0.25 * latency_ms + 0.75 * self._avg_latency_ms
        )

    def get_health(self, health_cfg: Optional[Dict[str, Any]] = None, simple_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        h = health_cfg or {}; s = simple_snapshot or {}
        preset = (s.get("preset") or "balanced") if isinstance(s, dict) else "balanced"
        period = int(s.get("detection_rate_ms", self.cfg.period_ms)) if isinstance(s, dict) else self.cfg.period_ms

        warn_factor = int(h.get("heartbeat_warn_factor", 3))
        fail_factor = int(h.get("heartbeat_fail_factor", 8))
        fps_warn_map = h.get("fps_warn_min", {"weak": 3, "balanced": 6, "strong": 8, "gpu": 10})
        lat_warn_map = h.get("latency_warn_ms", {"cpu": 300, "gpu": 150})

        now_ms = int(time.time() * 1000)
        since = None if self._last_detect_ms is None else (now_ms - self._last_detect_ms)
        hb_warn = period * warn_factor; hb_fail = period * fail_factor

        status = "green"; reason = None
        if since is None or since > hb_fail: status, reason = "red", "no_heartbeat"
        elif since > hb_warn: status, reason = "yellow", "slow_heartbeat"

        min_fps = float(fps_warn_map.get(preset, 6))
        if self._fps and self._fps < min_fps and status != "red":
            status, reason = "yellow", "low_fps"

        lat_warn = int(lat_warn_map.get("cpu", 300))
        if str(self.cfg.device or "").startswith("cuda") or str(self.cfg.provider).endswith("gpu"):
            lat_warn = int(lat_warn_map.get("gpu", 150))
        if self._avg_latency_ms and self._avg_latency_ms > lat_warn and status != "red":
            status, reason = "yellow", "high_latency"

        return {
            "status": status, "reason": reason,
            "fps": round(self._fps, 2), "avg_latency_ms": int(self._avg_latency_ms),
            "last_beat_ms": self._last_detect_ms, "profile": self.cfg.provider,
        }

    def get_runtime_params(self) -> Dict[str, Any]:
        rp = {
            "profile": self.cfg.provider,
            "input_size": self.cfg.input_size_preset or self._extract_input_preset_from_extra(self.cfg.extra),
            "detection_rate_ms": self.cfg.period_ms,
            "confidence_threshold": self.cfg.threshold,
            "max_objects": self.cfg.max_objects,
            "safe_mode.enabled": self.cfg.safe_mode_enabled,
            "safe_mode.top_k": self.cfg.safe_mode_top_k,
            "tracking_enabled": self.cfg.tracking_enabled,
            "allowed_labels": list(self.cfg.allowed_labels or []),
        }
        logger.info("[Detector.runtime] {}", rp)
        return rp
