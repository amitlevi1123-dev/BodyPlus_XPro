# core/object_detection/engine.py
# -------------------------------------------------------
# 🎯 מנוע זיהוי אובייקטים: Detect → Angle → (Track?) → Features → Payload
# מצב נוכחי: עקיבה כבויה כברירת־מחדל וללא ספאם לוגים כשאין מסלולים/אובייקטים.
# -------------------------------------------------------

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import time
import math
import threading

# ===== לוגים (שקטים כשאין צורך) =====
try:
    from core.logs import logger, od_event, od_fail, od_span
except Exception:
    try:
        from loguru import logger  # type: ignore
    except Exception:
        class _NullLogger:
            def info(self, *a, **k): ...
            def warning(self, *a, **k): ...
            def error(self, *a, **k): ...
            def debug(self, *a, **k): ...
        logger = _NullLogger()  # type: ignore

    def od_event(level: str, code: str, msg: str, **ctx):
        try:
            logger.log(level.upper(), f"[{code}] {msg} | ctx={ctx}")
        except Exception:
            pass
    def od_fail(code: str, msg: str, **ctx):
        try:
            logger.error(f"[{code}] {msg} | ctx={ctx}")
        except Exception:
            pass
    from contextlib import contextmanager
    @contextmanager
    def od_span(code: str, **ctx):
        t0 = time.time()
        ok_holder = {"ok": False, "extra": {}}
        try:
            logger.debug(f"[{code}] start | ctx={ctx}")
            class _S:
                def ok(self_, **extra): ok_holder.update({"ok": True, "extra": extra})
            yield _S()
        except Exception:
            logger.exception("[OD1999] unhandled exception | ctx={}".format(ctx))
            raise
        finally:
            dt = (time.time() - t0)*1000.0
            if ok_holder["ok"]:
                logger.info(f"[{code}] done OK | elapsed_ms={dt:.2f} | ctx={ctx} | extra={ok_holder['extra']}")
            else:
                logger.warning(f"[{code}] done (no explicit ok()) | elapsed_ms={dt:.2f} | ctx={ctx}")

# ייבוא יחסי/מוחלט
try:
    from .detector import ObjectDetectionConfig, DetectorState, DetectionItem, DetectorService
    from .angle import AngleResult, compute_angle_for_box, AngleConfig
    from .tracks import TrackerConfig, Tracker, Obs
    from .features import FeatureConfig, FeatureAugmentor
    from .config_loader import build_all_from_yaml
except Exception:
    from core.object_detection.detector import ObjectDetectionConfig, DetectorState, DetectionItem, DetectorService
    from core.object_detection.angle import AngleResult, compute_angle_for_box, AngleConfig
    from core.object_detection.tracks import TrackerConfig, Tracker, Obs
    from core.object_detection.features import FeatureConfig, FeatureAugmentor
    from core.object_detection.config_loader import build_all_from_yaml


def _now_ms() -> int:
    return int(time.time() * 1000)


class ObjectDetectionEngine:
    """
    Engine שמחבר את כל השכבות ומחזיר Payload אחיד.

    שינויי “שקט” מרכזיים:
    • עקיבה כבויה כברירת־מחדל (engine_tracking_enabled=False), ולא מחזירה לוגים OD1401/OD1402.
    • אין OD1502 על payload ריק כשאין דיטקציות — פשוט מחזירים payload מינימלי ושותקים.
    • נשארים לוגים חשובים: OD1000/OD1001/OD1020/OD1200/OD1201/OD1501 (רק כשיש אובייקטים).
    """

    # דגל פנימי: כשאין אובייקטים — לא לרשום שגיאה/אזהרה (שקט)
    _QUIET_WHEN_EMPTY: bool = True

    def __init__(
        self,
        detector_cfg: ObjectDetectionConfig,
        angle_cfg: AngleConfig,
        tracker_cfg: TrackerConfig,
        feature_cfg: FeatureConfig,
    ):
        # קונפיגים
        self.detector_cfg = detector_cfg
        self.ang_cfg = angle_cfg
        self.trk_cfg = tracker_cfg
        self.feat_cfg = feature_cfg

        # ברירות מחדל קשיחות
        for name, value in (
            ("tracking_enabled", False),        # ← כבוי כברירת־מחדל
            ("safe_mode_enabled", True),
            ("safe_mode_top_k", 6),
            ("period_ms", 200),
            ("threshold", 0.30),
            ("max_objects", 20),
            ("allowed_labels", []),
        ):
            if not hasattr(self.detector_cfg, name):
                try: setattr(self.detector_cfg, name, value)
                except Exception: pass

        # ודא שגם בקונפיג ה-Tracker עצמו מכובה כברירת-מחדל
        for name, value in (("enabled", False), ("min_score", 0.15)):  # ← enabled=False
            if not hasattr(self.trk_cfg, name):
                try: setattr(self.trk_cfg, name, value)
                except Exception: pass

        # שירותים
        self.detector = DetectorService(self.detector_cfg)
        self.tracker = Tracker(self.trk_cfg)
        self.features = FeatureAugmentor(self.feat_cfg)

        # מצב ריצה
        self._last_frame: Optional[Any] = None
        self._last_ts_ms: int = 0
        self._last_payload: Dict[str, Any] = {}
        self._last_tracks: List[Any] = []
        self._started: bool = False

        # Nonblocking
        self._busy = False
        self._lock = threading.Lock()

        # עקיבה ברמת Engine – כבויה כברירת־מחדל
        self._engine_tracking_enabled = False

        # לוג איניט תמציתי
        od_event(
            "INFO", "OD1000", "Engine init",
            provider=getattr(self.detector_cfg, "provider", "?"),
            threshold=getattr(self.detector_cfg, "threshold", None),
            engine_tracking=self._engine_tracking_enabled,
            det_period_ms=getattr(self.detector_cfg, "period_ms", None),
            max_objects=getattr(self.detector_cfg, "max_objects", None),
        )

    # -------- Lifecycle --------
    def start(self) -> None:
        with od_span("OD1000", step="start", provider=getattr(self.detector_cfg, "provider", "?")) as span:
            try:
                if hasattr(self.detector, "warmup"):
                    self.detector.warmup()
                self._started = True
                od_event("INFO", "OD1001", "model/provider ready", provider=getattr(self.detector_cfg, "provider", "?"))
                span.ok()
            except Exception as e:
                od_fail("OD1002", f"warmup failed: {type(e).__name__}", err=str(e))
                self._started = True  # לא חוסמים tick

    def stop(self) -> None:
        self._started = False
        logger.info("Engine stopped.")

    # -------- Public API --------
    def update_frame(self, frame_bgr: Any, ts_ms: Optional[int] = None) -> None:
        with od_span("OD1100", action="update_frame") as span:
            with self._lock:
                self._last_frame = frame_bgr
                self._last_ts_ms = _now_ms() if ts_ms is None else ts_ms
            if frame_bgr is None:
                od_fail("OD1101", "received None frame", ts_ms=self._last_ts_ms)
                return
            shp = getattr(frame_bgr, "shape", None)
            if shp is None or (isinstance(shp, tuple) and len(shp) < 2):
                od_fail("OD1102", "invalid frame shape/dtype", shape=str(shp), ts_ms=self._last_ts_ms)
                return
            span.ok(img_shape=str(shp), ts_ms=self._last_ts_ms)

    # ---- Admin API passthroughs ----
    def update_simple(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        try:
            updated = self.detector.update_simple(patch or {})
        except Exception as e:
            logger.error("Engine.update_simple -> detector.update_simple failed: {}", e)
            updated = {}

        # period_ms
        try:
            self.detector_cfg.period_ms = int(updated.get("detection_rate_ms", self.detector_cfg.period_ms))
        except Exception:
            pass

        # עקיבה ברמת Engine (אפשר לכבות/להדליק ידנית אם תרצה בעתיד)
        try:
            if "tracking_enabled" in (patch or {}):
                self._engine_tracking_enabled = bool(patch["tracking_enabled"])
        except Exception:
            pass

        return updated

    def get_simple(self) -> Dict[str, Any]:
        try:
            snap = self.detector.update_simple({})  # “patch” ריק כדי לקבל מצב נוכחי
            snap = dict(snap or {})
            snap.setdefault("tracking_enabled", bool(self._engine_tracking_enabled))
            if "safe_mode" not in snap:
                snap["safe_mode"] = {
                    "enabled": bool(getattr(self.detector_cfg, "safe_mode_enabled", True)),
                    "top_k": int(getattr(self.detector_cfg, "safe_mode_top_k", 6)),
                }
            return snap
        except Exception as e:
            logger.error("Engine.get_simple failed: {}", e)
            return {
                "input_size": getattr(self.detector_cfg, "input_size_preset", None),
                "detection_rate_ms": getattr(self.detector_cfg, "period_ms", None),
                "confidence_threshold": getattr(self.detector_cfg, "threshold", None),
                "max_objects": getattr(self.detector_cfg, "max_objects", None),
                "safe_mode": {
                    "enabled": getattr(self.detector_cfg, "safe_mode_enabled", True),
                    "top_k": getattr(self.detector_cfg, "safe_mode_top_k", 6),
                },
                "tracking_enabled": bool(self._engine_tracking_enabled),
                "allowed_labels": list(getattr(self.detector_cfg, "allowed_labels", []) or []),
            }

    def get_runtime_params(self) -> Dict[str, Any]:
        try:
            if hasattr(self.detector, "get_runtime_params"):
                rp = self.detector.get_runtime_params()  # type: ignore
                rp = dict(rp or {})
                rp.setdefault("safe_mode.enabled", getattr(self.detector_cfg, "safe_mode_enabled", True))
                rp.setdefault("safe_mode.top_k", getattr(self.detector_cfg, "safe_mode_top_k", 6))
                rp.setdefault("tracking_enabled", bool(self._engine_tracking_enabled))
                return rp
        except Exception as e:
            logger.error("Engine.get_runtime_params failed: {}", e)
        return {
            "profile": getattr(self.detector_cfg, "provider", None),
            "input_size": getattr(self.detector_cfg, "input_size_preset", None),
            "detection_rate_ms": getattr(self.detector_cfg, "period_ms", None),
            "confidence_threshold": getattr(self.detector_cfg, "threshold", None),
            "max_objects": getattr(self.detector_cfg, "max_objects", None),
            "safe_mode.enabled": getattr(self.detector_cfg, "safe_mode_enabled", True),
            "safe_mode.top_k": getattr(self.detector_cfg, "safe_mode_top_k", 6),
            "tracking_enabled": bool(self._engine_tracking_enabled),
            "allowed_labels": list(getattr(self.detector_cfg, "allowed_labels", []) or []),
        }

    def get_health(self, health_cfg: Optional[Dict[str, Any]] = None,
                   simple_snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        period = getattr(self.detector_cfg, "period_ms", 200) or 200
        try:
            if hasattr(self.detector, "get_health"):
                return self.detector.get_health(health_cfg or {}, simple_snapshot or {})  # type: ignore
        except Exception as e:
            logger.error("Engine.get_health failed: {}", e)
        return {
            "status": "green",
            "reason": None,
            "fps": round(1000.0 / float(period), 2),
            "avg_latency_ms": None,
            "last_beat_ms": None,
            "profile": getattr(self.detector_cfg, "provider", "unknown"),
        }

    # -------- Tick (sync) --------
    def tick(self) -> Tuple[List[Any], Dict[str, Any]]:
        if not self._started:
            try:
                self.start()
            except Exception as e:
                logger.warning("Engine.tick: start() failed (ignored): {}", e)

        with self._lock:
            frame = self._last_frame
            ts_ms = self._last_ts_ms or _now_ms()

        if frame is None:
            # פריים חסר באמת — זה כן שגיאה אמיתית
            od_fail("OD1101", "tick received None frame", ts_ms=ts_ms)
            payload = self._make_empty_payload(ok=False, ts_ms=ts_ms, err="no_frame")
            with self._lock:
                self._last_tracks, self._last_payload = [], payload
            return [], payload

        # 1) Detect
        det_t0 = time.time()
        with od_span("OD1200", ts_ms=ts_ms, profile=getattr(self.detector_cfg, "provider", "?")) as span:
            try:
                det_items: List[DetectionItem] = self.detector.detect(frame, ts_ms=ts_ms)
                det_ok = True
                det_err = None
            except RuntimeError as e:
                od_fail("OD1203", "runtime error during inference", err=str(e), provider=getattr(self.detector_cfg, "provider", "?"))
                det_items, det_ok, det_err = [], False, f"detect_runtime:{type(e).__name__}"
            except Exception as e:
                od_fail("OD1202", "unexpected error during inference", err=str(e))
                det_items, det_ok, det_err = [], False, f"detect_error:{type(e).__name__}"
            det_latency_ms = int((time.time() - det_t0) * 1000)
            od_event("INFO", "OD1201", "inference done", detections=len(det_items), latency_ms=det_latency_ms)
            span.ok(detections=len(det_items), latency_ms=det_latency_ms)

        # Fallback ל-devnull/sim
        try:
            prov = (getattr(self.detector_cfg, "provider", "") or "").lower()
            if prov in ("devnull", "sim") and not det_items:
                h, w = getattr(frame, "shape", (720, 1280, 3))[:2]
                t = time.time()
                cx = int((w * 0.5) + (w * 0.2) * math.sin(t))
                cy = int((h * 0.5) + (h * 0.2) * math.cos(t))
                bw, bh = int(w * 0.18), int(h * 0.28)
                x1, y1 = max(0, cx - bw // 2), max(0, cy - bh // 2)
                x2, y2 = min(w - 1, x1 + bw), min(h - 1, y1 + bh)
                det_items = [DetectionItem(label="dummy", score=1.0, box=(x1, y1, x2, y2))]
                det_ok = True
                det_err = None
                det_latency_ms = max(det_latency_ms, 5)
                od_event("INFO", "OD1900", "DEVNULL/SIM fallback generated dummy object",
                         w=w, h=h, cx=cx, cy=cy, box=(x1, y1, x2, y2))
        except Exception as _e:
            logger.warning("fallback synth failed: {}", _e)

        # 2) Angle → Obs
        obs_list: List[Obs] = []
        for d in det_items:
            angle_res: Optional[AngleResult] = None
            try:
                angle_res = compute_angle_for_box(frame, getattr(d, "box", None), self.ang_cfg)
            except Exception as e:
                od_event("WARNING", "OD1302", "compute_angle_for_box failed",
                         label=getattr(d, "label", "?"), err=str(e))
                angle_res = None

            angle_src_val = None if angle_res is None else getattr(angle_res, "ang_src", None)
            obs_list.append(
                Obs(
                    label=getattr(d, "label", None),
                    score=getattr(d, "score", None),
                    box=getattr(d, "box", None),
                    angle_deg=(None if angle_res is None else angle_res.angle_deg),
                    angle_quality=(None if angle_res is None else angle_res.quality),
                    angle_src=angle_src_val,
                )
            )

        # 3) Track — מכובה כברירת־מחדל וללא לוגים על “אפס מסלולים”
        with od_span("OD1400", ts_ms=ts_ms) as span:
            tracks: List[Any] = []
            try:
                if self._engine_tracking_enabled:
                    tracks = self.tracker.update(obs_list, ts_ms=ts_ms)
                    # אם תרצה בעתיד — אפשר להחזיר DEBUG קצר:
                    # od_event("DEBUG", "OD1401", "tracking updated", tracks=len(tracks))
                else:
                    # “עקבה” חד־פעמית שקטה (det-only) — בלי לוגים
                    for o in obs_list:
                        tracks.append({
                            "track_id": None,
                            "label": o.label,
                            "score": o.score,
                            "box": o.box,
                            "cx": None, "cy": None,
                            "cx_norm": None, "cy_norm": None,
                            "state": "det_only",
                            "age": 1,
                            "missed": 0,
                            "angle_deg": o.angle_deg,
                            "quality": o.angle_quality,
                            "angle_src": o.angle_src,
                            "stale": False,
                        })
                span.ok(tracks=len(tracks))
            except Exception as e:
                logger.error("Tracker.update failed: {}", e)
                tracks = []
                det_ok = False
                det_err = f"track_error:{type(e).__name__}"

        # 4) Features
        try:
            tracks = self.features.apply(tracks, ts_ms=ts_ms)
        except Exception as e:
            logger.warning("FeatureAugmentor.apply failed (ignored): {}", e)

        # 5) Build payload (שקט כשאין אובייקטים)
        payload = self._build_payload(tracks, ts_ms, det_ok, det_err, det_latency_ms)
        with self._lock:
            self._last_tracks = tracks
            self._last_payload = payload
        return tracks, payload

    # ------- Nonblocking -------

    def tick_nonblocking(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._tick_worker, daemon=True, name="ODTick").start()

    def _tick_worker(self) -> None:
        try:
            self.tick()
        except Exception as e:
            logger.error("tick_nonblocking worker failed: {}", e)
        finally:
            self._busy = False

    def get_last_result(self) -> Tuple[List[Any], Dict[str, Any]]:
        with self._lock:
            return list(self._last_tracks), dict(self._last_payload)

    # -------- Config helpers --------
    @classmethod
    def from_yaml(cls, yaml_path: str) -> "ObjectDetectionEngine":
        det_cfg, ang_cfg, trk_cfg, feat_cfg, adjusted = build_all_from_yaml(yaml_path)
        # ודא שגם בקובץ הקונפיג העקיבה תצא כבויה אם לא צוין אחרת
        try:
            setattr(trk_cfg, "enabled", bool(getattr(trk_cfg, "enabled", False)))
        except Exception:
            pass
        try:
            prov = getattr(det_cfg, "provider", "?")
            has_local_model = bool(getattr(det_cfg, "local_model", None) or getattr(det_cfg, "weights", None))
            od_event(
                "INFO", "OD1020", "config loaded",
                provider=prov,
                has_local_model=has_local_model,
                tracking_keys=list((adjusted.get("tracking") or {}).keys()),
                angle_keys=list((adjusted.get("angle") or {}).keys()),
            )
        except Exception:
            pass
        return cls(detector_cfg=det_cfg, angle_cfg=ang_cfg, tracker_cfg=trk_cfg, feature_cfg=feat_cfg)

    # -------- Payload helpers --------
    def _make_empty_payload(self, ok: bool, ts_ms: int, err: Optional[str]) -> Dict[str, Any]:
        return {
            "objects_version": getattr(self.feat_cfg, "objects_version", 1),
            "objects": [],
            "tracks": [],
            "detector_state": {
                "ok": ok,
                "provider": getattr(self.detector_cfg, "provider", None),
                "last_error": err,
                "last_ts_ms": ts_ms,
                "last_latency_ms": None,
                "training": {
                    "project": getattr(self.detector_cfg, "project", None),
                    "version": getattr(self.detector_cfg, "version", None),
                    "status": "unknown",
                    "last_update_ms": ts_ms,
                },
            },
        }

    def _build_payload(
        self,
        tracks: List[Any],
        ts_ms: int,
        ok: bool,
        err: Optional[str],
        det_latency_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        objects: List[Dict[str, Any]] = []
        for t in tracks:
            def get(field, default=None):
                return getattr(t, field, default) if hasattr(t, field) else (
                    t.get(field, default) if isinstance(t, dict) else default
                )
            objects.append({
                "track_id": get("track_id", get("id", None)),
                "label": get("label", None),
                "score": get("score", None),
                "box": get("box", None),
                "cx": get("cx", None),
                "cy": get("cy", None),
                "cx_norm": get("cx_norm", None),
                "cy_norm": get("cy_norm", None),
                "state": get("state", None),
                "age": get("age", None),
                "missed": get("missed", 0),
                "angle_deg": get("angle_deg", None),
                "angle_stale": get("angle_stale", False),
                "vx": get("vx", None),
                "vy": get("vy", None),
                "ang_vel": get("ang_vel", None),
                "quality": get("angle_quality", get("quality", None)),
                "angle_src": get("angle_src", None),
                "stale": get("stale", False),
                "updated_at_ms": ts_ms,
            })

        # מצב דיטקטור
        last_latency = det_latency_ms
        last_err = err
        ok_flag = ok
        try:
            det_state = getattr(self, "detector", None).state if hasattr(self, "detector") else None
            if isinstance(det_state, DetectorState):
                ok_flag = ok_flag and bool(getattr(det_state, "ok", True))
                if last_latency is None:
                    last_latency = getattr(det_state, "last_latency_ms", None)
                last_err = last_err or getattr(det_state, "last_error", None)
        except Exception:
            pass

        state: Dict[str, Any] = {
            "ok": ok_flag,
            "provider": getattr(self.detector_cfg, "provider", None),
            "last_error": last_err,
            "last_ts_ms": ts_ms,
            "last_latency_ms": last_latency,
            "training": {
                "project": getattr(self.detector_cfg, "project", None),
                "version": getattr(self.detector_cfg, "version", None),
                "status": "completed",
                "last_update_ms": ts_ms,
            },
        }

        result = {
            "objects_version": getattr(self.feat_cfg, "objects_version", 1),
            "objects": objects,
            "tracks": tracks,
            "detector_state": state,
        }

        # 🔇 שקט כשאין אובייקטים / אוקיי שקרי — לא לרשום OD1502
        if self._QUIET_WHEN_EMPTY and (not objects or not ok_flag):
            # אפשר להשאיר DEBUG מינימלי אם תרצה בעתיד:
            # od_event("DEBUG", "OD1500", "payload empty/quiet", objects=len(objects), ok=ok_flag, last_err=last_err)
            return result

        # יש תוכן → נרשום בנימוס
        od_event("INFO", "OD1501", "payload built", objects=len(objects), last_latency_ms=last_latency)
        return result
