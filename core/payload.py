# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 📦 BodyPlus_XPro — Canonical Payload v1.2.0  (UNDER 700 LINES)
# -----------------------------------------------------------------------------

from __future__ import annotations

import json
import time
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ===== Version =====
PAYLOAD_VERSION = "1.2.0"

# ===== Thresholds & Ranges =====
DEFAULT_QUALITY_THRESHOLD = 0.30   # איכות מינימלית למדד כדי להיחשב "תקף"
CONFIDENCE_THRESHOLD_LOW = 0.50    # מתחת לזה → low_confidence True

ANGLE_UNSIGNED_RANGE = (0.0, 200.0)     # מעלות מפרקים לא חתומות
ANGLE_SIGNED_RANGE   = (-180.0, 180.0)  # מעלות חתומות (ראש/טורסו וכו')
CONFIDENCE_RANGE     = (0.0, 1.0)
RATIO_RANGE          = (0.0, 10.0)

# =============================================================================
# Safe defaults
# =============================================================================

def _frame_defaults() -> Dict[str, Any]:
    return {"id": 0, "ts": 0, "w": 0, "h": 0, "fps": 0.0}

def _view_defaults() -> Dict[str, Any]:
    return {"mode": "unknown", "quality": 0.0, "camera": 0}

def _head_defaults() -> Dict[str, Any]:
    return {"yaw_deg": 0.0, "pitch_deg": 0.0, "roll_deg": 0.0, "confidence": 0.0, "ok": False}

def _objdet_defaults() -> Dict[str, Any]:
    return {
        "enabled": False,
        "profile": None,
        "count": 0,
        "objects": [],
        "detector_state": {"ok": False, "provider": "none", "last_error": None, "last_ts_ms": None, "last_latency_ms": None},
        "frame": {"w": 0, "h": 0, "ts_ms": 0, "mirrored": False},
        "fps": 0.0,
        "latency_ms": 0
    }

def _availability_defaults() -> Dict[str, bool]:
    return {
        "pose": False,
        "hands": False,
        "head": False,
        "objdet": False,
        "measurements": False,
        "scoring": False,
    }

def empty_payload() -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    return {
        "payload_version": PAYLOAD_VERSION,

        "frame": {
            "width": 0, "height": 0, "frame_id": 0,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        },

        "view": dict(_view_defaults()),

        "head": dict(_head_defaults()),

        "objdet": dict(_objdet_defaults()),

        # NOTE: כל המדדים החיים (כולל ידיים) תחת measurements
        "measurements": {},

        "scoring": {"score": None, "reason": "no_exercise_selected"},

        "availability": dict(_availability_defaults()),

        "meta": {
            "frame_id": 0,
            "created_at_ms": now_ms,
            "finalized_at_ms": now_ms,
            "pose_detected": False,
            "average_visibility": 0.0,
            "visible_points_count": 0,
            "confidence": 0.0,
            "quality_score": 0.0,
            "low_confidence": True,
            "exercise": None,
            "rep_count": 0,
            "set_count": 0,
        },

        "diagnostics": {
            "warnings": [],
            "errors": [],
            "notes": [],
            "measurements_count": 0,
            "missing_count": 0,
        },

        # תאימות אחורה (שטוח)
        "frame_id": 0,
        "ts": now_ms,
        "ts_ms": now_ms,
        "frame.w": 0,
        "frame.h": 0,
        "view_mode": "unknown",
        "view_score": 0.0,
        "average_visibility": 0.0,
        "visible_points_count": 0,
        "confidence": 0.0,
        "quality_score": 0.0,
        "low_confidence": True,
        "head_yaw_deg": 0.0,
        "head_pitch_deg": 0.0,
        "head_roll_deg": 0.0,
        "head_confidence": 0.0,
        "head_ok": 0.0,
    }

def ensure_schema(p: Dict[str, Any] | None) -> Dict[str, Any]:
    base = empty_payload()
    if not isinstance(p, dict):
        return base

    out = {**base, **p}
    out["frame"] = {**base["frame"], **(p.get("frame") or {})}
    out["view"] = {**base["view"], **(p.get("view") or {})}
    out["head"] = {**base["head"], **(p.get("head") or {})}
    out["objdet"] = {**base["objdet"], **(p.get("objdet") or {})}
    out["availability"] = {**base["availability"], **(p.get("availability") or {})}
    out["measurements"] = p.get("measurements") or {}

    # תאימות אחורה
    out["frame.w"] = out["frame"].get("width", 0)
    out["frame.h"] = out["frame"].get("height", 0)
    out["view_mode"] = out["view"].get("mode", "unknown")
    out["view_score"] = out["view"].get("quality", 0.0)

    # head aliases
    out["head_yaw_deg"] = out["head"].get("yaw_deg", 0.0)
    out["head_pitch_deg"] = out["head"].get("pitch_deg", 0.0)
    out["head_roll_deg"] = out["head"].get("roll_deg", 0.0)
    out["head_confidence"] = out["head"].get("confidence", 0.0)
    out["head_ok"] = 1.0 if out["head"].get("ok") else 0.0

    return out

# =============================================================================
# Data Contracts
# =============================================================================

@dataclass
class Measurement:
    key: str
    value: Optional[float]
    quality: float           # 0..1
    source: str              # "pose"/"hands"/"objdet"/"computed"
    unit: str = ""
    ts_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_public(self) -> Dict[str, Any]:
        return {"value": self.value, "quality": self.quality, "source": self.source, "unit": self.unit, "ts_ms": self.ts_ms}

@dataclass
class MissingMeasurement:
    key: str
    source: str
    reason: str
    note: Optional[str] = None

    def to_public(self) -> Dict[str, Any]:
        return {"source": self.source, "reason": self.reason, "note": self.note}

@dataclass
class ObjectDetection:
    track_id: int
    label: str
    score: float
    box: List[float]                 # [x1, y1, x2, y2] ∈ [0..1]
    angle_deg: Optional[float] = None
    features: Dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "label": self.label,
            "score": self.score,
            "box": self.box,
            "angle_deg": self.angle_deg,
            "features": self.features
        }

# =============================================================================
# Payload Builder
# =============================================================================

class Payload:
    def __init__(self) -> None:
        # Meta
        self.version: str = PAYLOAD_VERSION
        self.created_at_ms: int = int(time.time() * 1000)

        # Frame
        self.frame_id: int = 0
        self.frame_width: int = 0
        self.frame_height: int = 0
        self.frame_fps: float = 0.0

        # View/Confidence
        self.view_mode: str = "unknown"
        self.view_quality: float = 0.0
        self.average_visibility: float = 0.0
        self.visible_points_count: int = 0
        self.confidence: float = 0.0
        self.quality_score: float = 0.0
        self.low_confidence: bool = True

        # Pose/Hands/Head
        self.pose_detected: bool = False
        self.head_yaw_deg: Optional[float] = None
        self.head_pitch_deg: Optional[float] = None
        self.head_roll_deg: Optional[float] = None
        self.head_confidence: Optional[float] = None
        self.head_ok: bool = False

        # Measurements
        self._meas: Dict[str, Measurement] = {}
        self._miss: Dict[str, MissingMeasurement] = {}

        # Object Detection
        self.objdet_enabled: bool = False
        self.objdet_profile: Optional[str] = None
        self._objdet: List[ObjectDetection] = []
        self._objdet_state: Dict[str, Any] = {
            "ok": False, "provider": "none", "last_error": None, "last_ts_ms": None, "last_latency_ms": None
        }

        # Exercise & Scoring
        self.exercise_name: Optional[str] = None
        self.rep_count: int = 0
        self.set_count: int = 0
        self.form_score: Optional[float] = None
        self.form_score_reason: Optional[str] = None
        self.form_score_available: bool = False

        # Diagnostics
        self.warnings: List[str] = []
        self.errors: List[str] = []
        self.notes: List[str] = []

        # Finalize
        self._finalized: bool = False
        self.finalized_at_ms: Optional[int] = None

    # ===== Builder API =====

    def set_frame_info(self, width: int, height: int, frame_id: int = 0, fps: float = 0.0) -> "Payload":
        self.frame_width, self.frame_height, self.frame_id, self.frame_fps = int(width), int(height), int(frame_id), float(fps)
        return self

    def set_view(self, mode: str, quality: float = 0.0) -> "Payload":
        self.view_mode = mode
        self.view_quality = max(0.0, min(1.0, float(quality)))
        return self

    def set_pose_visibility(self, avg_visibility: float, visible_count: int) -> "Payload":
        self.average_visibility = max(0.0, min(1.0, float(avg_visibility)))
        self.visible_points_count = int(max(0, visible_count))
        self.confidence = self.average_visibility
        self.quality_score = round(self.average_visibility * 100.0, 2)
        self.low_confidence = self.average_visibility < CONFIDENCE_THRESHOLD_LOW
        return self

    def set_pose_detected(self, detected: bool) -> "Payload":
        self.pose_detected = bool(detected)
        return self

    def set_head(self,
                 yaw_deg: Optional[float] = None,
                 pitch_deg: Optional[float] = None,
                 roll_deg: Optional[float] = None,
                 confidence: Optional[float] = None,
                 ok: bool = False) -> "Payload":
        self.head_yaw_deg = yaw_deg
        self.head_pitch_deg = pitch_deg
        self.head_roll_deg = roll_deg
        self.head_confidence = confidence
        self.head_ok = bool(ok)
        return self

    def measure(self, key: str, value: Optional[float], *,
                quality: float = 1.0, source: str = "pose", unit: str = "") -> "Payload":
        if value is None:
            self.mark_missing(key, source=source, reason="not_computable")
            return self
        if not _is_finite(value):
            self.mark_missing(key, source=source, reason="invalid_value", note="NaN/Inf")
            return self
        if quality < DEFAULT_QUALITY_THRESHOLD:
            self.mark_missing(key, source=source, reason="low_quality", note=f"quality={quality:.2f}")
            return self

        self._meas[key] = Measurement(key=key, value=float(value), quality=float(quality), source=source, unit=unit)
        return self

    def mark_missing(self, key: str, *, source: str = "pose", reason: str = "not_available", note: Optional[str] = None) -> "Payload":
        self._miss[key] = MissingMeasurement(key=key, source=source, reason=reason, note=note)
        return self

    def set_objdet_profile(self, profile: str, enabled: bool = True) -> "Payload":
        self.objdet_profile = profile
        self.objdet_enabled = bool(enabled)
        return self

    def add_objdet(self, *, detections: Optional[List[Dict[str, Any]]] = None, state: Optional[Dict[str, Any]] = None) -> "Payload":
        if detections:
            for d in detections:
                self._objdet.append(
                    ObjectDetection(
                        track_id=int(d.get("track_id", d.get("id", -1))),
                        label=str(d.get("label", d.get("cls", "unknown"))),
                        score=float(d.get("score", d.get("conf", 0.0))),
                        box=list(d.get("box", [0, 0, 0, 0])),
                        angle_deg=d.get("angle_deg"),
                        features=d.get("features", {}),
                    )
                )
        if state:
            self._objdet_state.update(state)
        return self

    def set_exercise(self, name: str, *, rep_count: int = 0, set_count: int = 0) -> "Payload":
        self.exercise_name = name
        self.rep_count = int(rep_count)
        self.set_count = int(set_count)
        return self

    def add_warning(self, msg: str) -> "Payload":
        self.warnings.append(msg)
        return self

    def add_error(self, msg: str) -> "Payload":
        self.errors.append(msg)
        return self

    def add_note(self, msg: str) -> "Payload":
        self.notes.append(msg)
        return self

    # ===== Finalize & Policies =====

    def finalize(self) -> "Payload":
        if self._finalized:
            return self
        self.finalized_at_ms = int(time.time() * 1000)

        # Scoring policy
        self._apply_scoring_policy()

        # Validation warnings
        self._validate_measurements()

        self._finalized = True
        return self

    def _apply_scoring_policy(self) -> None:
        if not self.exercise_name:
            self.form_score_available = False
            self.form_score_reason = "no_exercise_selected"
            self.form_score = None
            return

        required = self._get_required_measurements_for_exercise(self.exercise_name)
        missing_req = [k for k in required if k not in self._meas]
        if missing_req:
            self.form_score_available = False
            head = ", ".join(missing_req[:3])
            tail = f" (+{len(missing_req)-3} more)" if len(missing_req) > 3 else ""
            self.form_score_reason = f"missing_required_measurements: {head}{tail}"
            self.form_score = None
            return

        low_q = [k for k in required if self._meas.get(k) and self._meas[k].quality < DEFAULT_QUALITY_THRESHOLD]
        if low_q:
            self.form_score_available = False
            self.form_score_reason = f"low_quality_measurements: {', '.join(low_q[:3])}"
            self.form_score = None
            return

        self.form_score_available = True
        self.form_score_reason = None

    def _get_required_measurements_for_exercise(self, exercise: str) -> List[str]:
        req = {
            "squat":       ["knee_angle_left", "knee_angle_right", "hip_angle_left", "hip_angle_right"],
            "deadlift":    ["hip_angle_left", "hip_angle_right", "torso_forward_deg"],
            "bench_press": ["elbow_angle_left", "elbow_angle_right", "shoulder_angle_left", "shoulder_angle_right"],
        }
        return req.get(exercise.lower(), [])

    def _validate_measurements(self) -> None:
        for key, m in self._meas.items():
            if m.value is None:
                continue
            if "_deg" in key or "angle" in key.lower():
                signed_like = any(s in key for s in ("delta", "signed", "torso", "spine", "head"))
                low, high = ANGLE_SIGNED_RANGE if signed_like else ANGLE_UNSIGNED_RANGE
                if not (low <= m.value <= high):
                    self.add_warning(f"{key}={m.value:.1f} out-of-range [{low},{high}]")
            if "confidence" in key or "quality" in key:
                if not (CONFIDENCE_RANGE[0] <= m.value <= CONFIDENCE_RANGE[1]):
                    self.add_warning(f"{key}={m.value:.2f} out-of-range [0..1]")
            if "_over_" in key or "ratio" in key.lower():
                if not (RATIO_RANGE[0] <= m.value <= RATIO_RANGE[1]):
                    self.add_warning(f"{key}={m.value:.2f} out-of-range ratio")

    # ----- Helpers (internal) -----

    def _has_hand_measurements(self) -> bool:
        # מזהה האם יש מדדי ידיים כדי להדליק availability.hands
        keys = (
            "wrist_flex_ext_left_deg", "wrist_flex_ext_right_deg",
            "wrist_radul_left_deg", "wrist_radul_right_deg",
            "hand_orientation_left", "hand_orientation_right"
        )
        return any(k in self._meas for k in keys) or any(k in self._miss for k in keys)

# =============================================================================
# Export (dict/json)
# =============================================================================

    def to_dict(self) -> Dict[str, Any]:
        # Flat measurements (legacy-style map)
        flat_meas: Dict[str, Optional[float]] = {k: v.value for k, v in self._meas.items()}
        for k in self._miss.keys():
            flat_meas.setdefault(k, None)

        # ObjDet block
        objects = [o.to_public() for o in self._objdet]
        objdet_block = {
            **_objdet_defaults(),
            "enabled": self.objdet_enabled,
            "profile": self.objdet_profile,
            "count": len(objects),
            "objects": objects,
            "detector_state": dict(self._objdet_state),
            "frame": {"w": self.frame_width, "h": self.frame_height, "ts_ms": self.finalized_at_ms or self.created_at_ms, "mirrored": False},
        }

        # Availability
        availability = {
            "pose": bool(self.pose_detected),
            "hands": self._has_hand_measurements(),   # <<< מתחשב במדדי ידיים בפועל
            "head": self.head_confidence is not None,
            "objdet": bool(self.objdet_enabled or len(objects) > 0),
            "measurements": len(self._meas) > 0 or len(self._miss) > 0,
            "scoring": bool(self.form_score_available),
        }

        payload: Dict[str, Any] = {
            "payload_version": self.version,

            "frame": {
                "width": self.frame_width,
                "height": self.frame_height,
                "frame_id": self.frame_id,
                "fps": self.frame_fps,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            },

            "view": {
                "mode": self.view_mode,
                "quality": self.view_quality,
                "camera": 0,
            },

            "head": {
                "yaw_deg": self.head_yaw_deg,
                "pitch_deg": self.head_pitch_deg,
                "roll_deg": self.head_roll_deg,
                "confidence": self.head_confidence,
                "ok": self.head_ok,
            },

            "objdet": objdet_block,

            # כל המדדים חיים כאן
            "measurements": flat_meas,

            "scoring": {
                "score": self.form_score,
                "reason": self.form_score_reason,
            },

            "availability": availability,

            "meta": {
                "frame_id": self.frame_id,
                "created_at_ms": self.created_at_ms,
                "finalized_at_ms": self.finalized_at_ms or self.created_at_ms,
                "pose_detected": self.pose_detected,
                "average_visibility": self.average_visibility,
                "visible_points_count": self.visible_points_count,
                "confidence": self.confidence,
                "quality_score": self.quality_score,
                "low_confidence": self.low_confidence,
                "exercise": self.exercise_name,
                "rep_count": self.rep_count,
                "set_count": self.set_count,
            },

            "diagnostics": {
                "warnings": list(self.warnings),
                "errors": list(self.errors),
                "notes": list(self.notes),
                "measurements_count": len(self._meas),
                "missing_count": len(self._miss),
            },

            "_measurements_detail": {k: m.to_public() for k, m in self._meas.items()},
            "_missing_detail": {k: m.to_public() for k, m in self._miss.items()},
        }

        # Backward-compat keys
        payload.update({
            "frame_id": self.frame_id,
            "ts": payload["meta"]["finalized_at_ms"],
            "ts_ms": payload["meta"]["finalized_at_ms"],

            "frame.w": self.frame_width,
            "frame.h": self.frame_height,

            "view_mode": self.view_mode,
            "view_score": self.view_quality,
            "average_visibility": self.average_visibility,
            "visible_points_count": self.visible_points_count,
            "confidence": self.confidence,
            "quality_score": self.quality_score,
            "low_confidence": self.low_confidence,

            "head_yaw_deg": self.head_yaw_deg if self.head_yaw_deg is not None else 0.0,
            "head_pitch_deg": self.head_pitch_deg if self.head_pitch_deg is not None else 0.0,
            "head_roll_deg": self.head_roll_deg if self.head_roll_deg is not None else 0.0,
            "head_confidence": self.head_confidence if self.head_confidence is not None else 0.0,
            "head_ok": 1.0 if self.head_ok else 0.0,
        })

        return payload

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_legacy_format(self) -> Dict[str, Any]:
        d = self.to_dict()
        for k in ("diagnostics", "_measurements_detail", "_missing_detail", "availability", "scoring", "head", "view"):
            d.pop(k, None)
        return d

# =============================================================================
# Helpers
# =============================================================================

def create_empty_payload() -> Payload:
    return Payload()

def _is_finite(x: Optional[float]) -> bool:
    if x is None:
        return False
    try:
        return math.isfinite(float(x))
    except Exception:
        return False

# =============================================================================
# Module Self-Test (manual)
# =============================================================================

if __name__ == "__main__":
    p = (Payload()
         .set_frame_info(1280, 720, frame_id=123, fps=25.0)
         .set_view("front", 0.9)
         .set_pose_detected(True)
         .set_pose_visibility(0.85, 26)
         .set_head(2.0, -1.0, 0.5, confidence=0.92, ok=True)
         # דוגמה למדדי ידיים מהקינמטיקס:
         .measure("wrist_flex_ext_left_deg",  12.3, quality=0.9, source="hands", unit="deg")
         .measure("wrist_flex_ext_right_deg", -5.8, quality=0.9, source="hands", unit="deg")
         # אופציונלי:
         # .measure("wrist_radul_left_deg",  8.1, quality=0.85, source="hands", unit="deg")
         # .measure("wrist_radul_right_deg", -6.4, quality=0.87, source="hands", unit="deg")
         .measure("knee_angle_left", 145.2, quality=0.88, unit="deg")
         .set_objdet_profile("onnx_cpu_416", enabled=True)
         .add_objdet(detections=[{"track_id": 1, "label": "barbell", "score": 0.82, "box": [0.1, 0.2, 0.4, 0.6]}])
         .set_exercise("squat")
         .finalize())
    print(p.to_json(indent=2))
