# core/object_detection/features.py
# -----------------------------------------------------------------------------
# BodyPlus XPro — Features (Angle Grace + Trail)
#
# מה זה עושה?
# - מוסיף "פיצ'רים" למסלולים:
#   1) Angle Grace: כשאין angle זמנית—משמר את האחרונה ומסמן angle_stale=True.
#   2) Trail: היסטוריית (cx,cy) קצרה לכל track_id לציור "שביל תנועה".
#
# מאפיינים:
# - עובד גם כשמסלולים הם אובייקטים (dataclass) וגם כשמסלולים הם dict.
# - מונע קריסות על שדות חסרים, מנקה זיכרון ממסלולים שנעלמו.
# - ה-ENGINE בונה את ה-payload; כאן רק מעדכנים שדות במסלולים.
# -----------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Deque, Tuple, List, Optional, Any
from collections import deque

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

# ---------------- Types ----------------
BBox = Tuple[int, int, int, int]

# ---------------- Config ----------------
@dataclass
class FeatureConfig:
    # Angle Grace (מונע קפיצות זווית בשגיאות רגעיות)
    angle_grace_frames: int = 3
    # Trail (שביל תנועה)
    trail_enabled: bool = True
    trail_seconds: float = 4.0
    trail_max_points: int = 180     # ~4 שניות בקצב גבוה
    # גירסת payload (נקראת ע"י ה-ENGINE)
    objects_version: int = 1
    # שדה הרחבות כללי (תאימות קדימה)
    extra: Dict[str, Any] = None

    def __post_init__(self):
        # קלמפ/ניקוי ערכים
        self.angle_grace_frames = max(0, int(self.angle_grace_frames))
        try:
            self.trail_seconds = float(self.trail_seconds)
        except Exception:
            self.trail_seconds = 4.0
        self.trail_max_points = max(8, int(self.trail_max_points))
        if self.extra is None:
            self.extra = {}
        logger.debug(
            "[Features.cfg] grace_frames={} trail_enabled={} trail_seconds={} trail_max_points={}",
            self.angle_grace_frames, self.trail_enabled, self.trail_seconds, self.trail_max_points
        )

# ---------------- Trail storage ----------------
@dataclass
class TrailPoint:
    x: float
    y: float
    ts_ms: int

class TrailBuffer:
    """שומר היסטוריית (cx,cy,ts) לכל track_id, מוגבלת בזמן ובכמות."""
    def __init__(self, horizon_sec: float, max_points: int):
        self.horizon_ms = int(max(0.5, float(horizon_sec)) * 1000)
        self.max_points = max(8, int(max_points))
        self._data: Dict[int, Deque[TrailPoint]] = {}
        logger.debug("[TrailBuffer.init] horizon_ms={} max_points={}", self.horizon_ms, self.max_points)

    def push(self, track_id: int, x: float, y: float, ts_ms: int) -> None:
        dq = self._data.setdefault(track_id, deque())
        dq.append(TrailPoint(x, y, ts_ms))
        # גבול לפי כמות
        while len(dq) > self.max_points:
            dq.popleft()
        # גבול לפי זמן
        cutoff = ts_ms - self.horizon_ms
        while dq and dq[0].ts_ms < cutoff:
            dq.popleft()
        logger.debug("[TrailBuffer.push] tid={} size={}", track_id, len(dq))

    def polyline(self, track_id: int) -> List[Tuple[float, float]]:
        dq = self._data.get(track_id)
        if not dq:
            return []
        return [(p.x, p.y) for p in dq]

    def prune_missing(self, alive_ids: List[int]) -> None:
        alive = set(int(i) for i in alive_ids)
        removed = 0
        for tid in list(self._data.keys()):
            if tid not in alive:
                del self._data[tid]
                removed += 1
        if removed:
            logger.debug("[TrailBuffer.prune] removed={} alive={}", removed, len(alive))

# ---------------- Angle Grace state ----------------
@dataclass
class _AngleHold:
    last_angle: Optional[float] = None
    last_frame_idx: int = -10  # אינדקס פריים אחרון שבו הייתה זווית

# ---------------- Helpers: safe get/set for obj or dict ----------------
def _get(o: Any, key: str, default: Any = None) -> Any:
    if isinstance(o, dict):
        return o.get(key, default)
    return getattr(o, key, default)

def _set(o: Any, key: str, value: Any) -> None:
    if isinstance(o, dict):
        o[key] = value
    else:
        setattr(o, key, value)

def _get_id(o: Any) -> Optional[int]:
    tid = _get(o, "track_id", None)
    if tid is None:
        tid = _get(o, "id", None)
    try:
        return None if tid is None else int(tid)
    except Exception:
        return None

def _get_center(o: Any) -> Tuple[Optional[float], Optional[float]]:
    cx = _get(o, "cx", None)
    cy = _get(o, "cy", None)
    # תמיכה במבנה חלופי center:[cx,cy]
    center = _get(o, "center", None)
    if (cx is None or cy is None) and isinstance(center, (list, tuple)) and len(center) >= 2:
        try:
            return float(center[0]), float(center[1])
        except Exception:
            pass
    try:
        return (float(cx) if cx is not None else None,
                float(cy) if cy is not None else None)
    except Exception:
        return None, None

# ---------------- FeatureAugmentor ----------------
class FeatureAugmentor:
    def __init__(self, cfg: FeatureConfig):
        self.cfg = cfg
        self._angle_hold: Dict[int, _AngleHold] = {}
        self._trail = TrailBuffer(cfg.trail_seconds, cfg.trail_max_points)
        self._fi: int = 0  # frame index פנימי לצורך Angle Grace
        logger.debug("[Features.init] created with cfg={}", cfg)

    # API שה-ENGINE משתמש בו
    def apply(self, tracks: List[Any], ts_ms: int) -> List[Any]:
        """
        מעדכן Angle Grace + Trail ומחזיר את רשימת ה-tracks (אין payload כאן).
        """
        self._fi += 1
        fi = self._fi
        logger.debug("[Features.apply] frame_idx={} n_tracks={}", fi, len(tracks))

        alive_ids: List[int] = []
        for tr in tracks:
            tid = _get_id(tr)
            if tid is None:
                # אין מזהה — דלג כדי לא לשבור את הזיכרון
                logger.debug("[Features.apply] skip track without id")
                continue
            alive_ids.append(tid)

            # --- Angle Grace ---
            hold = self._angle_hold.setdefault(tid, _AngleHold())
            angle_val = _get(tr, "angle_deg", None)

            if angle_val is not None:
                try:
                    angle_f = float(angle_val)
                    hold.last_angle = angle_f
                    hold.last_frame_idx = fi
                    _set(tr, "angle_stale", False)
                except Exception:
                    logger.debug("[Features.apply] angle parse failed tid={} val={}", tid, angle_val)
                    self._maybe_hold_angle(tr, hold, fi)
            else:
                self._maybe_hold_angle(tr, hold, fi)

            # --- Trail ---
            if self.cfg.trail_enabled:
                cx, cy = _get_center(tr)
                if cx is not None and cy is not None:
                    try:
                        self._trail.push(int(tid), float(cx), float(cy), int(ts_ms))
                    except Exception:
                        # לא נעצור את הזרימה על בעיית טיפוס
                        logger.debug("[Features.apply] trail push failed tid={} cx={} cy={}", tid, cx, cy)

        # נקה מסלולים שאינם פעילים כדי שלא יצטבר זיכרון
        self._trail.prune_missing(alive_ids)

        return tracks

    def _maybe_hold_angle(self, tr: Any, hold: _AngleHold, fi: int) -> None:
        """מיישם את מדיניות Angle Grace כאשר הזווית חסרה בפריים הנוכחי."""
        if hold.last_angle is not None and self.cfg.angle_grace_frames > 0:
            if (fi - hold.last_frame_idx) <= self.cfg.angle_grace_frames:
                _set(tr, "angle_deg", float(hold.last_angle))
                _set(tr, "angle_stale", True)
                return
        _set(tr, "angle_stale", False)

    # API קטן ל-UI לקבל polyline (לציור "שביל תנועה")
    def get_trail_polyline(self, track_id: int) -> List[Tuple[float, float]]:
        return self._trail.polyline(int(track_id))

    # ------- תאימות לאחור / דיבאג בלבד -------
    def update(
        self,
        tracks: List[Any],
        frame_size: Tuple[int, int],
        detector_state: Optional[Any] = None,
        now_ms: Optional[int] = None,
        frame_index: Optional[int] = None,
    ) -> Tuple[List[Any], Dict[str, Any]]:
        """
        תמיכה לאחור: מתנהג כמו גרסה ישנה שהחזירה גם payload.
        ה-ENGINE של היום לא משתמש בזה. נח לשימוש בבדיקות/דיבאג.
        """
        ts_ms = int(now_ms) if now_ms is not None else 0
        if frame_index is not None:
            self._fi = int(frame_index)
        tracks = self.apply(tracks, ts_ms=ts_ms)

        payload = {
            "objects_version": int(getattr(self.cfg, "objects_version", 1)),
            "objects": [],
            "detector_state": _pack_detector_state(detector_state),
        }
        for tr in tracks:
            tid = _get_id(tr)
            obj = {
                "track_id": tid,
                "label": _get(tr, "label", None),
                "state": _get(tr, "state", None),
                "stale": bool(_get(tr, "stale", False)),
                "score": float(_get(tr, "score", 0.0)) if _get(tr, "score", None) is not None else None,
                "box": _box_tuple(_get(tr, "box", (0, 0, 1, 1))),
                "cx": _get(tr, "cx", None),
                "cy": _get(tr, "cy", None),
                "cx_norm": _get(tr, "cx_norm", None),
                "cy_norm": _get(tr, "cy_norm", None),
                "age": _get(tr, "age", None),
                "missed": _get(tr, "missed", None),
                "angle_deg": _get(tr, "angle_deg", None),
                "angle_stale": bool(_get(tr, "angle_stale", False)),
                "updated_at_ms": ts_ms,
                "quality": _get(tr, "angle_quality", None),
                "ang_src": _get(tr, "angle_src", None),
            }
            payload["objects"].append(obj)
        return tracks, payload

# ---------------- Debug packers ----------------
def _box_tuple(b: BBox) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = b
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    if x2 <= x1:
        x2 = x1 + 1
    if y2 <= y1:
        y2 = y1 + 1
    return x1, y1, x2, y2

def _pack_detector_state(state: Optional[Any]) -> Dict[str, Any]:
    if not state:
        return {"ok": True, "last_latency_ms": None, "last_error": None, "provider": None, "last_ts_ms": None}
    return {
        "ok": bool(getattr(state, "ok", True)),
        "last_latency_ms": getattr(state, "last_latency_ms", None),
        "last_error": getattr(state, "last_error", None),
        "provider": getattr(state, "provider", None),
        "last_ts_ms": getattr(state, "last_ts_ms", None),
    }
