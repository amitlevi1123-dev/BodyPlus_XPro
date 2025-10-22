# core/object_detection/tracks.py
# -----------------------------------------------------------------------------
# BodyPlus XPro — Tracking (יציבות בלי "קפיצות")
#
# שיפורים מהותיים בגרסה זו:
# • TTL: Expire ב- >= במקום > כדי להיצמד למשמעות "מותר לפספס עד N פריימים".
# • החמרת הגנות טיפוסים ונורמליזציה לערכי קונפיג (לא שליליים).
# • דעיכת score במסלולים "missed" כדי לדחוק מסלולים ישנים כשמופיע חדש.
# • החלקת תיבה וזווית (EMA) + הגבלת קפיצה — כבעבר, אך עם הערות/ניקיון.
# • Matching נשאר גרידי מהיר; נוספו שומרי סף קטנים לבטיחות.
# -----------------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import math
import itertools
import time

__all__ = [
    "Obs", "TrackerConfig", "Track", "Tracker"
]

BBox = Tuple[int, int, int, int]

# -------------------- Data --------------------

@dataclass
class Obs:
    label: Optional[str]
    score: Optional[float] = 0.0       # עלול להגיע None → ננרמל ל-0.0
    box: BBox = (0, 0, 1, 1)
    angle_deg: Optional[float] = None
    angle_quality: Optional[float] = None
    angle_src: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TrackerConfig:
    appear_hits: int = 2
    ttl_frames: int = 12
    max_cost_per_match: float = 0.85
    w_iou: float = 0.6
    w_centroid: float = 0.3
    w_angle: float = 0.1
    smooth_alpha: float = 0.25
    max_jump_px: float = 48.0
    ang_max_jump_deg: float = 20.0
    vel_alpha: float = 0.5
    min_score: float = 0.8               # ✅ ברירת־מחדל קשיחה 0..1
    enforce_label_match: bool = False
    # שיפורים אופציונליים:
    decay_on_miss: float = 0.98          # דעיכת score לכל פריים "missed" (0.98 ≈ 2% ירידה)
    max_tracks: int = 128                # הגנה רכה — לא חובה, 0/שלילי = ללא הגבלה

@dataclass
class Track:
    track_id: int
    label: Optional[str]
    state: str
    score: float
    box: BBox
    cx: float
    cy: float
    cx_norm: Optional[float]
    cy_norm: Optional[float]
    angle_deg: Optional[float]
    vx: float = 0.0
    vy: float = 0.0
    ang_vel: float = 0.0
    angle_quality: Optional[float] = None
    angle_src: Optional[str] = None
    age: int = 0
    missed: int = 0
    hits: int = 1
    stale: bool = False
    updated_at_ms: Optional[int] = None

# -------------------- Tracker --------------------

class Tracker:
    def __init__(self, cfg: TrackerConfig):
        # נירמול קונפיג לבטיחות
        try: cfg.min_score = max(0.0, min(1.0, float(cfg.min_score)))
        except Exception: cfg.min_score = 0.8

        # משקולות לא שליליות
        try: cfg.w_iou = max(0.0, float(cfg.w_iou))
        except Exception: cfg.w_iou = 0.6
        try: cfg.w_centroid = max(0.0, float(cfg.w_centroid))
        except Exception: cfg.w_centroid = 0.3
        try: cfg.w_angle = max(0.0, float(cfg.w_angle))
        except Exception: cfg.w_angle = 0.1

        # ספים נוספים
        try: cfg.max_cost_per_match = float(cfg.max_cost_per_match)
        except Exception: cfg.max_cost_per_match = 0.85
        try: cfg.ttl_frames = int(cfg.ttl_frames)
        except Exception: cfg.ttl_frames = 12
        try: cfg.appear_hits = max(1, int(cfg.appear_hits))
        except Exception: cfg.appear_hits = 2
        try: cfg.max_tracks = int(cfg.max_tracks)
        except Exception: cfg.max_tracks = 128
        try: cfg.decay_on_miss = float(cfg.decay_on_miss)
        except Exception: cfg.decay_on_miss = 0.98

        self.cfg = cfg
        self._tracks: List[Track] = []
        self._id_counter = itertools.count(1)
        self._last_frame_size: Optional[Tuple[int, int]] = None

    # --- public API ---
    def update(self, observations: List[Obs], ts_ms: Optional[int] = None) -> List[Track]:
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)

        W, H = self._infer_frame_size(observations) or (None, None)
        if W is not None and H is not None:
            self._last_frame_size = (W, H)

        # ✅ סינון לפי min_score בבטחה (None→0.0)
        obs = [o for o in observations if (o.score or 0.0) >= self.cfg.min_score]

        # השוואה/שיוך
        assignments, unassigned_obs, unassigned_trk = self._match(obs, self._tracks, self._last_frame_size)

        # עדכון משויך
        for trk_idx, obs_idx in assignments:
            self._update_track_with_obs(self._tracks[trk_idx], obs[obs_idx], ts_ms)

        # מסלולים שלא קיבלו תצפית
        for trk_idx in unassigned_trk:
            self._update_track_missed(self._tracks[trk_idx], ts_ms)

        # תצפיות שלא שובצו → מסלולים חדשים
        for obs_idx in unassigned_obs:
            # הגנת עומס: אם max_tracks>0 והגענו לתקרה — נעדיף לא להציף
            if self.cfg.max_tracks > 0 and len(self._tracks) >= self.cfg.max_tracks:
                # מחיקה רכה של המסלול הכי ישן/חלש כדי לפנות מקום (לפי score ואז missed)
                try:
                    self._tracks.sort(key=lambda t: (t.score, -t.missed, -t.age))
                    self._tracks.pop(0)
                except Exception:
                    pass
            self._spawn_track(obs[obs_idx], ts_ms)

        self._expire_dead_tracks()
        # מחזיר את כל המסלולים שאינם expired
        return [t for t in self._tracks if t.state != "expired"]

    # ------------- matching -------------

    def _match(self, obs: List[Obs], tracks: List[Track], frame_size: Optional[Tuple[int, int]]):
        if not obs or not tracks:
            return [], list(range(len(obs))), list(range(len(tracks)))

        W, H = frame_size if frame_size is not None else (None, None)
        costs: List[List[float]] = []
        for tr in tracks:
            row = []
            for ob in obs:
                # אילוץ תווית כשמבוקש
                if self.cfg.enforce_label_match and tr.label and ob.label and tr.label != ob.label:
                    row.append(1e9)  # מונע התאמה
                else:
                    c = self._pair_cost(tr, ob, W, H)
                    row.append(c if math.isfinite(c) else 1e9)
            costs.append(row)

        assigned_trk, assigned_obs, assignments = set(), set(), []
        triples = [(ti, oi, costs[ti][oi]) for ti in range(len(tracks)) for oi in range(len(obs))]
        triples.sort(key=lambda t: t[2])  # גרידי: מהעלויות הנמוכות לגבוהות

        for ti, oi, c in triples:
            if c > self.cfg.max_cost_per_match:
                break
            if ti in assigned_trk or oi in assigned_obs:
                continue
            assigned_trk.add(ti)
            assigned_obs.add(oi)
            assignments.append((ti, oi))

        unassigned_obs = [i for i in range(len(obs)) if i not in assigned_obs]
        unassigned_trk = [i for i in range(len(tracks)) if i not in assigned_trk]
        return assignments, unassigned_obs, unassigned_trk

    def _pair_cost(self, tr: Track, ob: Obs, W: Optional[int], H: Optional[int]) -> float:
        iou = _iou(tr.box, ob.box)
        di = 1.0 - iou                              # קטן=טוב
        dc = _norm_centroid_dist(tr.cx, tr.cy, ob.box, W, H)  # 0..1
        da = _angle_diff_deg(tr.angle_deg, ob.angle_deg) / 180.0  # 0..1
        # שילוב משקולות
        return self.cfg.w_iou * di + self.cfg.w_centroid * dc + self.cfg.w_angle * da

    # ------------- track updates -------------

    def _update_track_with_obs(self, tr: Track, ob: Obs, ts_ms: int):
        tr.age += 1
        tr.missed = 0
        tr.hits += 1
        tr.stale = False
        tr.updated_at_ms = ts_ms

        if tr.state == "initializing" and tr.hits >= self.cfg.appear_hits:
            tr.state = "confirmed"
        elif tr.state == "missed":
            tr.state = "confirmed"

        # החלקת תיבה + הגבלת קפיצה
        bx = _box_to_tuple(ob.box)
        tr.box = _ema_box(tr.box, bx, self.cfg.smooth_alpha, self.cfg.max_jump_px)
        tr.cx, tr.cy = _center_of_box(tr.box)

        # נירמול מרכזים (אם יש גודל פריים מהיסטוריה)
        if self._last_frame_size is not None:
            W, H = self._last_frame_size
            tr.cx_norm = tr.cx / float(W)
            tr.cy_norm = tr.cy / float(H)
        else:
            tr.cx_norm = tr.cy_norm = None

        # מהירות (EMA) בפיקסלים/פריים
        vx_now = tr.cx - getattr(tr, "_prev_cx", tr.cx)
        vy_now = tr.cy - getattr(tr, "_prev_cy", tr.cy)
        tr.vx = _ema(tr.vx, vx_now, self.cfg.vel_alpha)
        tr.vy = _ema(tr.vy, vy_now, self.cfg.vel_alpha)
        tr._prev_cx, tr._prev_cy = tr.cx, tr.cy

        # זווית (מוגבלת קפיצה) + מהירות זוויתית (ang_vel)
        if ob.angle_deg is not None:
            ang_now = _clamp_angle_jump(tr.angle_deg, ob.angle_deg, self.cfg.ang_max_jump_deg)
            tr.ang_vel = 0.0 if tr.angle_deg is None else _ema(tr.ang_vel, _angle_signed_diff(ang_now, tr.angle_deg), self.cfg.vel_alpha)
            tr.angle_deg = ang_now

        # איכות/מקור זווית (אם קיימים)
        if ob.angle_quality is not None:
            tr.angle_quality = float(ob.angle_quality)
        elif "quality" in ob.extra:
            try:
                tr.angle_quality = float(ob.extra["quality"])
            except Exception:
                pass

        if ob.angle_src is not None:
            tr.angle_src = str(ob.angle_src)
        elif "ang_src" in ob.extra:
            tr.angle_src = str(ob.extra["ang_src"])

        # ניקוד
        s = float(ob.score or 0.0)
        tr.score = max(tr.score, s) if tr.state != "initializing" else s
        tr.label = ob.label

    def _update_track_missed(self, tr: Track, ts_ms: int):
        tr.age += 1
        tr.missed += 1
        tr.stale = True
        tr.updated_at_ms = ts_ms

        # העברת מצבים
        if tr.state == "confirmed":
            tr.state = "missed"

        # דעיכת score עדינה לדחיקת מסלולים ישנים
        try:
            if 0.0 < self.cfg.decay_on_miss < 1.0:
                tr.score *= self.cfg.decay_on_miss
        except Exception:
            pass

        # מחיקה כשהגיע ה-TTL (>= כדי שמשמעות ttl_frames תהיה “מותר לפספס עד N”)
        if tr.missed >= self.cfg.ttl_frames:
            tr.state = "expired"

    def _spawn_track(self, ob: Obs, ts_ms: int):
        x1, y1, x2, y2 = _box_to_tuple(ob.box)
        cx = (x1 + x2) * 0.5
        cy = (y1 + y2) * 0.5
        if self._last_frame_size is not None:
            W, H = self._last_frame_size
            cxn = cx / float(W)
            cyn = cy / float(H)
        else:
            cxn = cyn = None

        tr = Track(
            track_id=next(self._id_counter),
            label=ob.label,
            state="initializing",
            score=float(ob.score or 0.0),
            box=(x1, y1, x2, y2),
            cx=cx, cy=cy,
            cx_norm=cxn, cy_norm=cyn,
            angle_deg=ob.angle_deg,
            vx=0.0, vy=0.0, ang_vel=0.0,
            age=1, missed=0, hits=1,
            stale=False, updated_at_ms=ts_ms,
            angle_quality=(float(ob.angle_quality) if ob.angle_quality is not None else
                           (float(ob.extra["quality"]) if "quality" in ob.extra else None)),
            angle_src=(str(ob.angle_src) if ob.angle_src is not None else
                       (str(ob.extra["ang_src"]) if "ang_src" in ob.extra else None)),
        )
        self._tracks.append(tr)

    def _expire_dead_tracks(self):
        self._tracks = [t for t in self._tracks if t.state != "expired"]

    # ------------- frame size guess -------------

    def _infer_frame_size(self, observations: List[Obs]) -> Optional[Tuple[int, int]]:
        if not observations:
            return None
        max_x = max_y = 0
        for ob in observations:
            x1, y1, x2, y2 = _box_to_tuple(ob.box)
            max_x = max(max_x, x1, x2)
            max_y = max(max_y, y1, y2)
        W = max(1, max_x + 1)
        H = max(1, max_y + 1)
        if self._last_frame_size is not None:
            W = max(W, self._last_frame_size[0])
            H = max(H, self._last_frame_size[1])
        return (W, H)

# ---------------- help funcs ----------------

def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    a_area = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    b_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = a_area + b_area - inter
    if union <= 0:
        return 0.0
    return inter / float(union)

def _center_of_box(box: BBox) -> Tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5

def _norm_centroid_dist(cx: float, cy: float, box_b: BBox,
                        W: Optional[int], H: Optional[int]) -> float:
    bx, by = _center_of_box(box_b)
    if not W or not H or W <= 1 or H <= 1:
        d = math.hypot(bx - cx, by - cy)
        return float(min(1.0, d / 640.0))
    dx = (bx - cx) / float(W)
    dy = (by - cy) / float(H)
    d = math.hypot(dx, dy)
    return float(min(1.0, d * 4.0))

def _angle_diff_deg(a: Optional[float], b: Optional[float]) -> float:
    if a is None or b is None:
        return 180.0
    d = abs((a - b) % 180.0)
    return min(d, 180.0 - d)

def _angle_signed_diff(a: float, b: float) -> float:
    d = (a - b) % 180.0
    if d > 90.0:
        d -= 180.0
    return d

def _ema(prev: float, new: float, alpha: float) -> float:
    return (1.0 - alpha) * prev + alpha * new

def _box_to_tuple(box: BBox) -> BBox:
    x1, y1, x2, y2 = map(int, box)
    if x2 <= x1:
        x2 = x1 + 1
    if y2 <= y1:
        y2 = y1 + 1
    return (x1, y1, x2, y2)

def _ema_box(prev: BBox, newb: BBox, alpha: float, max_jump_px: float) -> BBox:
    def _clamp(pv, nv):
        if abs(nv - pv) > max_jump_px:
            return pv + math.copysign(max_jump_px, nv - pv)
        return nv
    x1 = _clamp(prev[0], newb[0]); y1 = _clamp(prev[1], newb[1])
    x2 = _clamp(prev[2], newb[2]); y2 = _clamp(prev[3], newb[3])
    sx1 = int(round(_ema(prev[0], x1, alpha))); sy1 = int(round(_ema(prev[1], y1, alpha)))
    sx2 = int(round(_ema(prev[2], x2, alpha))); sy2 = int(round(_ema(prev[3], y2, alpha)))
    if sx2 <= sx1: sx2 = sx1 + 1
    if sy2 <= sy1: sy2 = sy1 + 1
    return (sx1, sy1, sx2, sy2)

def _clamp_angle_jump(prev: Optional[float], new: float, max_jump: float) -> float:
    if prev is None:
        return float(new) % 180.0
    d = _angle_signed_diff(new, prev)
    if abs(d) > max_jump:
        new = prev + math.copysign(max_jump, d)
    new = new % 180.0
    if new < 0:
        new += 180.0
    return new
