# ------------------------------------------------------- config_loader.py
# טוען YAML (detector/tracking/angle/features) ומחזיר קונפיג סלחני קדימה.
# • תומך גם במבנה ישן (sections) וגם במבנה פרופילים עם profiles + active_profile/env_override.
# • תומך בשכבת simple.* (כולל presets ו-override_profile) — החלה על הקונפיג בזמן בנייה.
# • מתעלם ממפתחות לא מוכרים (נשמרים ב-extra).
# • תומך באליאסים ישנים (match_weights→w_* , tracker→tracking, model→detector).
# • מבטיח טיפוסים וערכי ברירת מחדל בטוחים.
# • פונקציות עיקריות: build_all_from_yaml / load_object_detection_config
# -------------------------------------------------------

from __future__ import annotations
import os, math
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterable, List, Optional, TypeVar, Tuple
from types import SimpleNamespace

# ===== לוגים (עדיפות דרך core.logs; נפילה ל-loguru/print ללא שינוי התנהגות) =====
try:
    from core.logs import logger as _logger, od_event as _od_event, od_fail as _od_fail
except Exception:
    _logger = None
    _od_event = None
    _od_fail = None

try:
    from loguru import logger as _loguru_logger  # סוגר פינה אם core.logs לא קיים
except Exception:
    _loguru_logger = None

def _log(msg: str) -> None:
    """לוג כללי לא חוסם — לא משנה זרימה/התנהגות."""
    try:
        if _logger is not None:
            _logger.info(msg)
            return
        if _loguru_logger is not None:
            _loguru_logger.info(msg)
            return
    except Exception:
        pass
    try:
        print(msg)
    except Exception:
        pass

def _od_info(code: str, msg: str, **ctx) -> None:
    try:
        if _od_event:
            _od_event("INFO", code, msg, **ctx)
            return
        # fallback: נרשום עדיין אינפורמציה עם קוד
        if _logger:
            _logger.info(f"[{code}] {msg} | ctx={ctx}")
            return
        if _loguru_logger:
            _loguru_logger.info(f"[{code}] {msg} | ctx={ctx}")
            return
    except Exception:
        pass
    _log(f"[{code}] {msg} | ctx={ctx}")

def _od_warn(code: str, msg: str, **ctx) -> None:
    try:
        if _od_event:
            _od_event("WARNING", code, msg, **ctx)
            return
        if _logger:
            _logger.warning(f"[{code}] {msg} | ctx={ctx}")
            return
        if _loguru_logger:
            _loguru_logger.warning(f"[{code}] {msg} | ctx={ctx}")
            return
    except Exception:
        pass
    _log(f"[{code}] {msg} | ctx={ctx}")

def _od_err(code: str, msg: str, **ctx) -> None:
    try:
        if _od_fail:
            _od_fail(code, msg, **ctx)
            return
        if _logger:
            _logger.error(f"[{code}] {msg} | ctx={ctx}")
            return
        if _loguru_logger:
            _loguru_logger.error(f"[{code}] {msg} | ctx={ctx}")
            return
    except Exception:
        pass
    _log(f"[{code}] {msg} | ctx={ctx}")

try:
    import yaml
except Exception:
    yaml = None

T = TypeVar("T")

# ---------------- paths & yaml ----------------

def _abspath(path: str) -> str:
    if os.path.isabs(path):
        return os.path.normpath(path)
    here = os.path.abspath(os.path.dirname(__file__))                 # .../core/object_detection
    proj_root = os.path.abspath(os.path.join(here, "..", ".."))
    candidates = [
        os.path.abspath(os.path.join(proj_root, path)),
        os.path.abspath(os.path.join(here, path)),
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.normpath(c)
    just_name = os.path.basename(path)
    alt = os.path.join(here, "config", just_name) if "config" not in path else os.path.join(here, just_name)
    if os.path.exists(alt):
        return os.path.normpath(alt)
    return os.path.normpath(candidates[0])

def load_yaml(path: str) -> Dict[str, Any]:
    full = _abspath(path)
    if not os.path.exists(full):
        raise FileNotFoundError(f"YAML not found: {full}")
    if yaml is None:
        raise RuntimeError("PyYAML not installed. Run: pip install pyyaml")
    with open(full, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be dict")
    keys = sorted(list(data.keys()))
    _log(f"[config] loaded YAML: {full}")
    _log(f"[config] top-level keys: {keys}")
    _od_info("OD1020", "config YAML loaded", path=full, keys=len(keys))
    return data

# ---------------- helpers ----------------

def _partition_keys(src: Dict[str, Any], allowed: Iterable[str]):
    allowed_set = set(allowed)
    known = {k: v for k, v in src.items() if k in allowed_set}
    unknown = {k: v for k, v in src.items() if k not in allowed_set}
    return known, unknown

def _coerce_types(cls, known: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(known)
    for f in fields(cls):
        if f.name not in out or out[f.name] is None:
            continue
        v = out[f.name]
        try:
            t = f.type
            is_opt = getattr(t, "__origin__", None) is Optional
            base = t.__args__[0] if is_opt else t
            if base is int:
                out[f.name] = int(v)
            elif base is float:
                out[f.name] = float(v)
            elif base is bool:
                if isinstance(v, str):
                    out[f.name] = v.strip().lower() in ("1", "true", "yes", "on")
                else:
                    out[f.name] = bool(v)
        except Exception:
            pass
    return out

def _dataclass_from_dict(cls, data: Dict[str, Any], *, strict: bool = False, name: str = ""):
    if data is None:
        data = {}
    flds = {f.name for f in fields(cls)}
    known, unknown = _partition_keys(data, flds)
    if "extra" in flds and unknown:
        known["extra"] = {**known.get("extra", {}), **unknown}
        unknown = {}
    if unknown and strict:
        # נרשום לפני שמחזירים חריגה — לא משנה לוגיקה
        _od_err("OD1021", f"{cls.__name__} unknown keys", keys=sorted(unknown.keys()))
        raise KeyError(f"{cls.__name__} unknown keys: {sorted(unknown.keys())}")
    if unknown:
        _log(f"[config:{name or cls.__name__}] ignored keys: {sorted(unknown.keys())}")
    try:
        obj = cls(**known)  # type: ignore
    except TypeError as e:
        _log(f"[config:{name or cls.__name__}] coercion fallback due to {e}")
        obj = cls(**_coerce_types(cls, known))  # type: ignore
    _log(f"[config:{name or cls.__name__}] accepted keys: {sorted(list(known.keys()))}")
    return obj

def _ns(d: Dict[str, Any]) -> SimpleNamespace:
    def conv(x):
        if isinstance(x, dict): return SimpleNamespace(**{k: conv(v) for k, v in x.items()})
        if isinstance(x, list): return [conv(v) for v in x]
        return x
    return conv(d)

# ---------------- dataclasses ----------------

@dataclass
class AngleConfig:
    min_quality_for_angle: float = 0.2
    hough_theta: float = math.pi / 180.0
    hough_rho: float = 1.0
    hough_threshold: int = 50
    hough_min_line_len: int = 30
    hough_max_line_gap: int = 10
    canny_low: int = 50
    canny_high: int = 150
    blur_kernel: int = 3
    edge_dilate_iter: int = 0
    hough_enabled: bool = True
    max_roi_px: int = 0
    min_edge_pixels: int = 25
    pca_min_var_ratio: float = 0.8
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, strict: bool = False):
        src = dict(d or {})
        if "hough_theta_deg" in src:
            try:
                src["hough_theta"] = math.radians(float(src.pop("hough_theta_deg")))
            except Exception:
                _log("[config:angle] invalid hough_theta_deg")
        if "hough_theta_rad" in src and "hough_theta" not in src:
            try:
                src["hough_theta"] = float(src.pop("hough_theta_rad"))
            except Exception:
                _log("[config:angle] invalid hough_theta_rad")
        return _dataclass_from_dict(cls, src, strict=strict, name="angle")

# TrackerConfig import
try:
    from .tracks import TrackerConfig
except ImportError:
    from core.object_detection.tracks import TrackerConfig

def _tracker_config_from_dict(d: Dict[str, Any], *, strict: bool = False):
    src = dict(d or {})
    for alt in ("ttl", "life", "life_frames"):
        if alt in src and "ttl_frames" not in src:
            src["ttl_frames"] = src.pop(alt)
    for alt in ("hits", "appear", "appear_confirms", "confirm_hits"):
        if alt in src and "appear_hits" not in src:
            src["appear_hits"] = src.pop(alt)
    for alt in ("enforce_label", "label_match", "strict_label"):
        if alt in src and "enforce_label_match" not in src:
            src["enforce_label_match"] = src.pop(alt)

    mw = src.get("match_weights") or {}
    def _adopt(dst: str, mw_key: Optional[str], *alts: str):
        if dst in src: return
        for a in alts:
            if a in src:
                src[dst] = src.pop(a); return
        if mw_key and mw_key in mw:
            src[dst] = mw[mw_key]
    _adopt("w_iou", "iou", "iou_weight", "weight_iou")
    _adopt("w_centroid", "centroid", "centroid_weight", "weight_centroid")
    _adopt("w_angle", "angle", "angle_weight", "weight_angle")

    try:
        if "min_score" in src:
            src["min_score"] = max(0.0, min(1.0, float(src["min_score"])))
    except Exception:
        src["min_score"] = 0.8

    return _dataclass_from_dict(TrackerConfig, src, strict=strict, name="tracking")

TrackerConfig.from_dict = classmethod(lambda cls, d, *, strict=False: _tracker_config_from_dict(d, strict=strict))

@dataclass
class ObjectDetectionConfig:
    enabled: bool = True
    provider: str = "devnull"
    api_base: Optional[str] = None
    workspace: Optional[str] = None
    project: Optional[str] = None
    version: Optional[str] = None
    threshold: float = 0.35
    overlap: float = 0.45
    max_objects: int = 8
    timeout_ms: int = 2500
    period_ms: int = 400
    clip_to_frame: bool = True
    dev_allow_no_api_key: bool = True
    weights: Optional[str] = None

    # YOLO/ONNX
    device: Optional[str] = None
    onnx_path: Optional[str] = None
    input_size: Optional[List[int]] = None

    # 🔽 שדות ברירת-מחדל חשובים כדי למנוע AttributeError בקוד
    tracking_enabled: bool = False
    safe_mode_enabled: bool = True
    safe_mode_top_k: int = 6
    input_size_preset: Optional[str] = None

    # ספים/תוויות
    threshold_default: float = 0.35
    thresholds: Dict[str, float] = field(default_factory=dict)
    allowed_labels: List[str] = field(default_factory=lambda: ["barbell", "dumbbell"])
    label_map: Dict[str, str] = field(default_factory=dict)

    performance_budget: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, strict: bool = False):
        src = dict(d or {})

        for alt in ("model_provider", "backend", "engine"):
            if alt in src and "provider" not in src:
                src["provider"] = src.pop(alt)

        if "local_model" in src and not src.get("weights"):
            src["weights"] = src["local_model"]
        if "onnx_path" in src and not src.get("weights"):
            src["weights"] = src["onnx_path"]

        for n in ("threshold", "overlap"):
            if n in src:
                try: src[n] = float(src[n])
                except Exception: pass
        for n in ("max_objects", "timeout_ms", "period_ms", "safe_mode_top_k"):
            if n in src:
                try: src[n] = int(src[n])
                except Exception: pass
        for n in ("enabled", "clip_to_frame", "dev_allow_no_api_key",
                  "tracking_enabled", "safe_mode_enabled"):
            if n in src:
                try:
                    v = src[n]
                    src[n] = (str(v).strip().lower() in ("1","true","yes","on")) if isinstance(v, str) else bool(v)
                except Exception:
                    pass

        return _dataclass_from_dict(cls, src, strict=strict, name="detector")

@dataclass
class FeatureConfig:
    angle_grace_frames: int = 3
    trail_enabled: bool = True
    trail_seconds: float = 4.0
    trail_max_points: int = 180
    objects_version: int = 1
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, strict: bool = False):
        return _dataclass_from_dict(cls, d or {}, strict=strict, name="features")

# ---------------- enforcement helpers ----------------

def _force_local_if_disabled(det_cfg: ObjectDetectionConfig) -> ObjectDetectionConfig:
    try:
        prov = (det_cfg.provider or "").lower().strip()
    except Exception:
        prov = ""
    disable_rf = os.getenv("DISABLE_ROBOFLOW", "0").strip() == "1"
    looks_remote = prov in ("roboflow", "http", "https")

    if disable_rf and looks_remote:
        tmp = ObjectDetectionConfig.from_dict({**vars(det_cfg)})
        tmp.provider = "yolov8"
        tmp.weights = tmp.weights or tmp.__dict__.get("local_model") or "yolov8n.pt"
        tmp.extra = dict(tmp.extra or {})
        tmp.extra.setdefault("imgsz", 384)
        tmp.extra.setdefault("allow_any_label", True)
        tmp.device = "cpu"
        tmp.threshold = max(0.35, float(tmp.threshold or 0.35))
        tmp.period_ms = max(150, int(tmp.period_ms or 180))
        _log(f"[config] DISABLE_ROBOFLOW=1 → forcing local YOLO (weights={tmp.weights}, imgsz={tmp.extra['imgsz']})")
        _od_warn("OD1020", "forcing local YOLO due to DISABLE_ROBOFLOW=1",
                 weights=tmp.weights, imgsz=tmp.extra["imgsz"], device=tmp.device)
        return tmp
    return det_cfg

# ---------------- simple helpers ----------------

def _parse_input_size_preset(preset: Optional[str]) -> Tuple[Optional[str], Optional[int], Optional[List[int]]]:
    """
    מחזיר: (input_size_preset, yolo_imgsz, onnx_input_size)
    384p → ( "384p", 384, None )
    """
    if not preset or not isinstance(preset, str):
        return None, None, None
    s = preset.strip().lower()
    if s.endswith("p"):
        try:
            n = int(s[:-1])
            if 160 <= n <= 1280:
                return s, n, None
        except Exception:
            return None, None, None
    return s, None, None

def _apply_simple_overrides(det_cfg: ObjectDetectionConfig,
                            trk_cfg: TrackerConfig,
                            features_cfg: FeatureConfig,
                            raw: Dict[str, Any],
                            profile_name: str) -> Dict[str, Any]:
    """
    מחיל שכבת simple.* על הקונפיגים. מחזיר צילום simple שהוחל בפועל.
    """
    simple = dict((raw.get("simple") or {}))
    presets = dict(simple.get("presets") or {})
    sel = (simple.get("preset") or "").strip().lower()
    snap: Dict[str, Any] = {}

    # presets: נטען ערכי בסיס
    chosen = {}
    if sel and sel in presets:
        chosen = dict(presets[sel] or {})
    # נדרוס ב-overrides ישירים (simple.*)
    for k in ("input_size", "detection_rate_ms", "confidence_threshold", "max_objects",
              "tracking_enabled", "allowed_labels", "safe_mode"):
        if k in simple:
            chosen[k] = simple[k]

    # input_size
    inp = chosen.get("input_size", None)
    preset_str, yolo_imgsz, onnx_input = _parse_input_size_preset(inp) if inp is not None else (None, None, None)
    if preset_str is not None:
        setattr(det_cfg, "input_size_preset", preset_str)
        det_cfg.extra = dict(det_cfg.extra or {})
        if yolo_imgsz is not None:
            det_cfg.extra["imgsz"] = int(yolo_imgsz)
    # detection_rate_ms → period_ms
    if "detection_rate_ms" in chosen and chosen["detection_rate_ms"] is not None:
        try: det_cfg.period_ms = max(80, int(chosen["detection_rate_ms"]))
        except Exception: pass
    # confidence_threshold → threshold
    if "confidence_threshold" in chosen and chosen["confidence_threshold"] is not None:
        try: det_cfg.threshold = float(chosen["confidence_threshold"])
        except Exception: pass
    # max_objects
    if "max_objects" in chosen and chosen["max_objects"] is not None:
        try: det_cfg.max_objects = int(chosen["max_objects"])
        except Exception: pass
    # tracking_enabled
    if "tracking_enabled" in chosen:
        try:
            val = bool(chosen["tracking_enabled"])
            setattr(det_cfg, "tracking_enabled", val)
            setattr(trk_cfg, "enabled", val)
        except Exception:
            pass
    # allowed_labels
    if "allowed_labels" in chosen and isinstance(chosen["allowed_labels"], list):
        det_cfg.allowed_labels = [str(x) for x in chosen["allowed_labels"]]
    # safe_mode
    sm = chosen.get("safe_mode", None)
    if isinstance(sm, dict):
        if "enabled" in sm:
            setattr(det_cfg, "safe_mode_enabled", bool(sm["enabled"]))
        if "top_k" in sm:
            try: setattr(det_cfg, "safe_mode_top_k", int(sm["top_k"]))
            except Exception: pass

    # צילום מצב שהוחל בפועל
    snap = {
        "preset": sel or None,
        "profile": profile_name,
        "input_size": getattr(det_cfg, "input_size_preset", None),
        "detection_rate_ms": getattr(det_cfg, "period_ms", None),
        "confidence_threshold": getattr(det_cfg, "threshold", None),
        "max_objects": getattr(det_cfg, "max_objects", None),
        "safe_mode": {
            "enabled": getattr(det_cfg, "safe_mode_enabled", True if sm is not None else True),
            "top_k": getattr(det_cfg, "safe_mode_top_k", (sm or {}).get("top_k", 6)),
        },
        "tracking_enabled": getattr(det_cfg, "tracking_enabled", getattr(trk_cfg, "enabled", True)),
        "allowed_labels": list(getattr(det_cfg, "allowed_labels", []) or []),
    }
    _od_info("OD1020", "simple overrides applied",
             preset=snap["preset"], imgsz=getattr(det_cfg, "extra", {}).get("imgsz", None),
             detection_rate_ms=snap["detection_rate_ms"], threshold=snap["confidence_threshold"],
             tracking_enabled=snap["tracking_enabled"])
    return snap

# ---------------- core builders ----------------

def _apply_aliases_top(raw: Dict[str, Any]) -> Dict[str, Any]:
    alias_map = {
        "angles": "angle",
        "tracker": "tracking",
        "track": "tracking",
        "feature": "features",
        "model": "detector",
    }
    adjusted: Dict[str, Any] = {}
    moved = []
    for k, v in raw.items():
        alias = alias_map.get(k, k)
        if alias != k:
            moved.append(f"{k}→{alias}")
        if isinstance(v, dict) and alias in ("angle", "tracking", "features", "detector", "ui", "health", "simple"):
            adjusted.setdefault(alias, {})
            adjusted[alias].update(v)
        else:
            adjusted[alias] = v
    if moved:
        _log(f"[config] moved sections: {moved}")
    return adjusted

def _select_profile(raw: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    בוחר פרופיל פעיל לפי env_override / DETECTOR_PROFILE / active_profile.
    מחזיר (profile_name, profile_dict).
    """
    profiles = raw.get("profiles", {}) or {}
    if not profiles:
        return "(legacy)", {}

    env_key = (raw.get("env_override") or "DETECTOR_PROFILE").strip()
    env_profile = os.getenv(env_key, "").strip() or os.getenv("DETECTOR_PROFILE", "").strip()

    simple = raw.get("simple") or {}
    override_profile = str(simple.get("override_profile") or "").strip()
    active_profile = override_profile or env_profile or raw.get("active_profile") or next(iter(profiles.keys()), None)

    if not active_profile or active_profile not in profiles:
        _od_err("OD1011", "active profile missing/unknown",
                requested=active_profile or None, available=list(profiles.keys()))
        raise ValueError(f"Unknown or missing profile '{active_profile}'. Available: {list(profiles.keys())}")

    _od_info("OD1010", "profile selected", profile=active_profile)
    return active_profile, dict(profiles[active_profile] or {})

def _finalize_detector_dict(det_dict: Dict[str, Any]) -> Dict[str, Any]:
    det = dict(det_dict or {})
    if "local_model" in det and "weights" not in det:
        det["weights"] = det["local_model"]
    if "onnx_path" in det and "weights" not in det:
        det["weights"] = det["onnx_path"]
    for n in ("threshold", "overlap"):
        if n in det:
            try: det[n] = float(det[n])
            except Exception: pass
    for n in ("max_objects", "timeout_ms", "period_ms"):
        if n in det:
            try: det[n] = int(det[n])
            except Exception: pass
    return det

def _inject_class_names_from_yaml(det_cfg: ObjectDetectionConfig, adjusted_raw: Dict[str, Any]) -> None:
    """
    אם יש classes ב-YAML (למשל ["barbell","dumbbell"]), נכניס אותם ל-detector.extra["class_names"]
    כדי שה-ONNX/YoloV8 יקבל שמות מחלקה עקביים בלי להגדיר ידנית.
    """
    classes = adjusted_raw.get("classes")
    if isinstance(classes, list) and classes:
        det_cfg.extra = dict(det_cfg.extra or {})
        det_cfg.extra["class_names"] = [str(x) for x in classes]
        _log(f"[config] injected class_names from YAML classes ({len(classes)} classes)")

# ---------------- build_all_from_yaml ----------------

def build_all_from_yaml(path: str):
    """
    • מכבד profiles + active_profile/env_override + simple.* (כולל presets/override_profile).
    • אם אין profiles — מתנהג כמו גרסה ישנה (legacy).
    • מחזיר: (det_cfg, ang_cfg, trk_cfg, feat_cfg, adjusted_dict)
    """
    raw = load_yaml(path)
    adjusted = _apply_aliases_top(raw)
    _log(f"[config] sections detected: {sorted(list(adjusted.keys()))}")

    # אם אין profiles → זרימה ישנה
    if "profiles" not in adjusted:
        det_section = _finalize_detector_dict(adjusted.get("detector", {}) or {})
        det_cfg = ObjectDetectionConfig.from_dict(det_section, strict=False)
        det_cfg = _force_local_if_disabled(det_cfg)

        ang_cfg = AngleConfig.from_dict(adjusted.get("angle", {}) or {}, strict=False)
        trk_cfg = TrackerConfig.from_dict(adjusted.get("tracking", {}) or {}, strict=False)
        feat_cfg = FeatureConfig.from_dict(adjusted.get("features", {}) or {}, strict=False)

        # החלת simple אם קיים גם ב-legacy:
        simple_snap = {}
        if "simple" in adjusted:
            simple_snap = _apply_simple_overrides(det_cfg, trk_cfg, feat_cfg, adjusted, "(legacy)")

        _inject_class_names_from_yaml(det_cfg, adjusted)

        adjusted["_meta"] = {"active_profile": "(legacy)", "provider": det_cfg.provider,
                             "env_override": adjusted.get("env_override", "DETECTOR_PROFILE")}
        adjusted["simple_snapshot"] = simple_snap

        _od_info("OD1020", "config built (legacy)",
                 provider=det_cfg.provider, profile="(legacy)",
                 tracking_enabled=getattr(trk_cfg, "enabled", True),
                 imgsz=getattr(det_cfg, "extra", {}).get("imgsz", None))
        return det_cfg, ang_cfg, trk_cfg, feat_cfg, adjusted

    # עם פרופילים
    profile_name, prof = _select_profile(adjusted)
    enabled = bool(prof.get("enabled", True))
    det_dict = _finalize_detector_dict((prof.get("detector") or {}))
    tracking_dict = adjusted.get("tracking", {}) or {}
    angle_dict = adjusted.get("angle", {}) or {}
    features_dict = adjusted.get("features", {}) or {}

    det_cfg = ObjectDetectionConfig.from_dict(det_dict, strict=False)
    det_cfg.enabled = enabled
    det_cfg = _force_local_if_disabled(det_cfg)

    ang_cfg = AngleConfig.from_dict(angle_dict, strict=False)
    trk_cfg = TrackerConfig.from_dict(tracking_dict, strict=False)
    feat_cfg = FeatureConfig.from_dict(features_dict, strict=False)

    # החלת simple.* (כולל override_profile שכבר נלקח בחשבון)
    simple_snap = _apply_simple_overrides(det_cfg, trk_cfg, feat_cfg, adjusted, profile_name)

    # הזרקת שמות מחלקות מה-YAML (classes -> extra.class_names)
    _inject_class_names_from_yaml(det_cfg, adjusted)

    # לצורך Admin UI/Health/Wiring
    adjusted["_meta"] = {
        "active_profile": profile_name,
        "provider": det_cfg.provider,
        "enabled": enabled,
        "env_override": adjusted.get("env_override", "DETECTOR_PROFILE"),
    }
    adjusted["simple_snapshot"] = simple_snap

    # העברה שקופה של בלוקים עבור UI/health/binding
    for key in ("health", "ui", "wiring_check_fields", "features", "classes", "ui_label_map"):
        if key in adjusted and adjusted[key] is None:
            adjusted[key] = {}

    _od_info("OD1020", "config built (profile)",
             profile=profile_name, provider=det_cfg.provider,
             tracking_enabled=getattr(trk_cfg, "enabled", True),
             imgsz=getattr(det_cfg, "extra", {}).get("imgsz", None))
    return det_cfg, ang_cfg, trk_cfg, feat_cfg, adjusted

# ---------------- load_object_detection_config ----------------

def load_object_detection_config(path: str = "core/object_detection/object_detection.yaml") -> SimpleNamespace:
    """
    עטיפה נוחה שמחזירה SimpleNamespace עם כל הבלוקים + _meta,
    מתאימה לשימושים שבהם רוצים מבנה "קריא" ולא רק dataclasses.
    """
    det, ang, trk, feat, adjusted = build_all_from_yaml(path)
    ui = adjusted.get("ui", {}) if isinstance(adjusted, dict) else {}
    health = adjusted.get("health", {}) if isinstance(adjusted, dict) else {}
    simple_snapshot = adjusted.get("simple_snapshot", {}) if isinstance(adjusted, dict) else {}
    classes = adjusted.get("classes", []) if isinstance(adjusted, dict) else []
    ui_label_map = adjusted.get("ui_label_map", {}) if isinstance(adjusted, dict) else {}
    wiring = adjusted.get("wiring_check_fields", []) if isinstance(adjusted, dict) else []
    ns = {
        "enabled": True if det.enabled is None else det.enabled,
        "detector": det,
        "tracking": trk,
        "angle": ang,
        "features": feat,
        "ui": ui,
        "health": health,
        "simple": simple_snapshot,
        "classes": classes,
        "ui_label_map": ui_label_map,
        "wiring_check_fields": wiring,
        "_meta": adjusted.get("_meta", {}),
    }
    _od_info("OD1020", "object detection config namespace ready",
             provider=det.provider, profile=ns["_meta"].get("active_profile"))
    return _ns(ns)
