# -------------------------------------------------------
# 👁️ נראות וזווית צילום (View) למנוע ProCoach
#
# מטרות הקובץ:
# 1) לבדוק אם נקודות גוף נראות מספיק (confidence ≥ threshold) לפני חישוב מדדים.
# 2) להעריך את זווית הצילום (view):
#    - 'front' = צילום מקדימה
#    - 'back'  = צילום מאחורה
#    - 'side'  = צילום מהצד
#    - 'unknown' = לא ניתן להכריע
#
# שיטות ההכרעה:
# - יחס רוחב/גובה בין כתפיים ואגן (dx/dy).
# - יחס רוחב כתפיים/אגן לעומת אורך הטורסו (רוחב/אורך) – Fast Path לצד.
# - שימוש בפנים: א-סימטריית אוזניים + היסט אף מול כתפיים → ציון yaw (פנייה הצידה).
# - הבחנה בין front/back לפי סדר אופקי (x) של כתף/אגן שמאל/ימין.
#
# פונקציות עיקריות:
# - visible_joints(kps, required, thr): בודקת נראות נקודות חובה.
# - shoulders_width_px / hips_width_px / _torso_length_px: עזרי סקייל.
# - estimate_view(kps): מחזירה mode (front/side/back/unknown) וציון ביטחון.
# - view_is_side(kps): מחזירה True/False אם מדובר בצילום צד.
# - compute_if_visible(...): מריצה חישוב רק אם הנקודות נראות וה־view תואם.
# - compute_visibility_gate(...): החסם הכללי למדידות, מחזיר (ok, quality).
#
# שיפורים בגרסה זו:
# - Fast-Path לזיהוי "side" לפי יחס רוחב/אורך טורסו (פחות תלוי ברזולוציה; טוב גם ב־720p).
# - ספי החלטה רגישים יותר באזור האפור (1.00..1.25) עם הטיית yaw לצד.
# - החמרה עדינה נגד ריצודים (side_bias) כשיש אינדיקציה חלקית לצד.
# -------------------------------------------------------

from __future__ import annotations
from typing import Dict, Tuple, Iterable, Callable, Optional, Set
import math

from .geometry import distance

Keypoint = Tuple[float, float, float]  # (x, y, conf)


# ----------------------------- עזרי גישה -----------------------------

def _get(kps: Dict[str, Keypoint], name: str) -> Optional[Keypoint]:
    v = kps.get(name)
    if not v or len(v) != 3:
        return None
    x, y, c = float(v[0]), float(v[1]), float(v[2])
    return (x, y, c)

def _conf(kps: Dict[str, Keypoint], name: str, default: float = 0.0) -> float:
    p = _get(kps, name)
    return p[2] if p else default


# ----------------------------- נראות נקודות -----------------------------

def visible_joints(kps: Dict[str, Keypoint],
                   required: Iterable[str],
                   thr: float = 0.6) -> bool:
    for name in required:
        p = _get(kps, name)
        if p is None or p[2] < thr:
            return False
    return True


# ----------------------------- עזרי סקייל -----------------------------

def shoulders_width_px(kps: Dict[str, Keypoint], thr: float = 0.6) -> Optional[float]:
    ls = _get(kps, "left_shoulder")
    rs = _get(kps, "right_shoulder")
    if not ls or not rs or min(ls[2], rs[2]) < thr:
        return None
    return distance((ls[0], ls[1]), (rs[0], rs[1]))

def hips_width_px(kps: Dict[str, Keypoint], thr: float = 0.6) -> Optional[float]:
    lh = _get(kps, "left_hip")
    rh = _get(kps, "right_hip")
    if not lh or not rh or min(lh[2], rh[2]) < thr:
        return None
    return distance((lh[0], lh[1]), (rh[0], rh[1]))

def _torso_length_px(kps: Dict[str, Keypoint], thr: float = 0.6) -> Optional[float]:
    """
    אורך טורסו = מרחק בין מרכז הכתפיים למרכז האגן.
    משמש לנורמליזציה של רוחב (כתפיים/אגן) → מאפשר זיהוי צד גם ברזולוציה נמוכה.
    """
    ls = _get(kps, "left_shoulder"); rs = _get(kps, "right_shoulder")
    lh = _get(kps, "left_hip");      rh = _get(kps, "right_hip")
    if not (ls and rs and lh and rh):
        return None
    if min(ls[2], rs[2], lh[2], rh[2]) < thr:
        return None
    mid_sh_x = 0.5 * (ls[0] + rs[0]); mid_sh_y = 0.5 * (ls[1] + rs[1])
    mid_hp_x = 0.5 * (lh[0] + rh[0]); mid_hp_y = 0.5 * (lh[1] + rh[1])
    return distance((mid_sh_x, mid_sh_y), (mid_hp_x, mid_hp_y))


# ----------------------------- עזרי View/Yaw -----------------------------

def _line_dx_dy(kps: Dict[str, Keypoint], a: str, b: str, thr: float) -> Optional[Tuple[float, float]]:
    pa = _get(kps, a)
    pb = _get(kps, b)
    if not pa or not pb or min(pa[2], pb[2]) < thr:
        return None
    dx = abs(pa[0] - pb[0])
    dy = abs(pa[1] - pb[1])
    return dx, dy

def _front_back_vote(kps: Dict[str, Keypoint], thr: float = 0.6) -> Optional[str]:
    vote = []
    ls = _get(kps, "left_shoulder")
    rs = _get(kps, "right_shoulder")
    if ls and rs and min(ls[2], rs[2]) >= thr:
        vote.append("front" if ls[0] > rs[0] else "back")

    lh = _get(kps, "left_hip")
    rh = _get(kps, "right_hip")
    if lh and rh and min(lh[2], rh[2]) >= thr:
        vote.append("front" if lh[0] > rh[0] else "back")

    if not vote:
        return None
    f = vote.count("front"); b = vote.count("back")
    if f > b: return "front"
    if b > f: return "back"
    return None

def _yaw_score_head(kps: Dict[str, Keypoint], thr: float = 0.5) -> float:
    """
    ציון YAW ∈ [0..1] משילוב:
    - ear_asym: א-סימטריה ב־confidence של האוזניים
    - nose_offset_ratio: היסט אפי מול מרכז כתפיים ביחס לרוחב כתפיים
    """
    le, re = _get(kps, "left_ear"), _get(kps, "right_ear")
    ln, rn = (le[2] if le else 0.0), (re[2] if re else 0.0)
    ear_sum = (ln + rn)
    ear_asym = abs(ln - rn) / ear_sum if ear_sum > 1e-6 else 0.0

    ls = _get(kps, "left_shoulder")
    rs = _get(kps, "right_shoulder")
    nose = _get(kps, "nose")
    shoulders_w = None
    nose_offset_ratio = 0.0
    if ls and rs and min(ls[2], rs[2]) >= thr:
        shoulders_w = distance((ls[0], ls[1]), (rs[0], rs[1]))
    if shoulders_w and shoulders_w > 1e-3 and nose and nose[2] >= thr:
        midx = 0.5 * (ls[0] + rs[0])
        nose_offset_ratio = min(1.0, abs(nose[0] - midx) / shoulders_w)

    score = 0.65 * ear_asym + 0.35 * nose_offset_ratio
    return max(0.0, min(1.0, score))


# ----------------------------- קביעת View -----------------------------

def estimate_view(kps: Dict[str, Keypoint], thr: float = 0.6) -> Tuple[str, float]:
    """
    מחזיר (mode, score):
    - Fast-Path: אם רוחב הכתפיים/אגן קטן ביחס לאורך הטורסו → 'side'.
    - אחרת: לוגיקת dx/dy + yaw + אזור אפור עם הטיות עדינות.
    ספים (מומלץ להתחיל איתם):
      * width_norm ≤ 0.55          → side (0.80+)
      * 0.55 < width_norm ≤ 0.70   → נטייה לצד (side_bias)
      * ratio := dx_sum/dy_sum
         - ratio ≤ 1.00            → side
         - 1.00 < ratio < 1.25     → אזור אפור (מוכרע ע"י yaw/side_bias)
         - ratio ≥ 1.25            → front/back
    """
    sh = _line_dx_dy(kps, "left_shoulder", "right_shoulder", thr)
    hp = _line_dx_dy(kps, "left_hip", "right_hip", thr)

    if sh is None and hp is None:
        return "unknown", 0.0

    # ---------- Fast-Path: side לפי יחס רוחב/אורך ----------
    sh_w = shoulders_width_px(kps, thr=thr) or 0.0
    hp_w = hips_width_px(kps, thr=thr) or 0.0
    torso_len = _torso_length_px(kps, thr=thr) or 0.0

    side_bias = 0.0
    if torso_len > 0.0:
        width_norm = max(sh_w, hp_w) / max(30.0, torso_len)  # 30px כדי למנוע יחס קיצוני בזום-אין
        if width_norm <= 0.55:
            return "side", 0.80
        elif width_norm <= 0.70:
            side_bias = 0.15  # נטייה לצד – תשמש בהמשך

    # ---------- לוגיקה קיימת (dx/dy + yaw) ----------
    dx_sum = 0.0; dy_sum = 0.0
    if sh: dx_sum += sh[0]; dy_sum += sh[1]
    if hp: dx_sum += hp[0]; dy_sum += hp[1]

    # אם אין כמעט "רוחב" אבל יש טייה אנכית גדולה → צד
    if dy_sum > 0 and dx_sum / dy_sum <= 1.0 / 1.6:
        score = min(1.0, (dy_sum - dx_sum) / max(1.0, dy_sum) + side_bias)
        return "side", float(max(0.55, score))

    if dy_sum == 0.0:
        if dx_sum == 0.0:
            return "unknown", 0.0
        fb = _front_back_vote(kps, thr=thr)
        score = min(1.0, max(0.0, dx_sum / (dx_sum + 50.0)))
        return (fb if fb else "unknown"), float(score)

    ratio = dx_sum / dy_sum
    yaw = _yaw_score_head(kps, thr=max(0.5, thr - 0.1))

    # --- SIDE ברור ---
    if ratio <= 1.00:
        base = max(0.0, min(1.0, (1.00 - ratio) / 1.00))
        score = min(1.0, base + 0.25 * yaw + side_bias)
        return "side", float(max(0.55, score))

    # --- FRONT/BACK ברור ---
    if ratio >= 1.25:
        fb = _front_back_vote(kps, thr=thr)
        base = max(0.0, min(1.0, (ratio - 1.25) / 0.9))
        # אם הראש מסובב מאוד ועדיין ratio רק מעט מעל הסף – אפשר לגלוש לצד
        if yaw >= 0.85 and base < 0.35:
            return "side", float(max(0.60, 0.40 + side_bias))
        return (fb if fb else "unknown"), float(min(1.0, base + 0.10 * (1.0 - yaw)))

    # --- אזור אפור: 1.00 < ratio < 1.25 ---
    if (yaw >= 0.45) or (side_bias > 0.0):
        closeness = (1.25 - ratio) / 0.25  # 0..1 – כמה קרוב לצד
        score = min(1.0, 0.45 + 0.45 * max(yaw, 0.40) + 0.30 * max(0.0, closeness) + side_bias)
        return "side", float(max(0.50, score))

    # לא מספיק ראיות – unknown עם ציון נטייה חלש
    drift = ratio - 1.125
    score = max(0.0, 1.0 - abs(drift) / 0.25)
    return "unknown", float(score)


def view_is_side(kps: Dict[str, Keypoint], thr: float = 0.6) -> bool:
    mode, _ = estimate_view(kps, thr=thr)
    return mode == "side"


# ----------------------------- Gate כללי -----------------------------

def _view_allows(mode_needed: Set[str], mode_current: str, is_side: bool) -> bool:
    if "any" in mode_needed:
        return True
    if "side" in mode_needed:
        return mode_current == "side"
    if "back" in mode_needed:
        return mode_current == "back"
    if "front" in mode_needed:
        return mode_current == "front"
    return False


def compute_if_visible(kps: Dict[str, Keypoint],
                       required: Iterable[str],
                       fn: Callable[[Dict[str, Keypoint]], object],
                       thr: float = 0.6,
                       views: Iterable[str] = ("any",)) -> Optional[object]:
    req = list(required)
    if not visible_joints(kps, req, thr=thr):
        return None

    mode, _score = estimate_view(kps, thr=thr)
    is_side = (mode == "side")
    if not _view_allows(set(v.lower() for v in views), mode, is_side):
        return None

    try:
        return fn(kps)
    except Exception:
        return None


def compute_visibility_gate(kps: dict,
                            required: list,
                            thr: float = 0.6,
                            views=("any",),
                            view_mode: str = "unknown"):
    """
    חסם כללי לפני חישוב מדד:
    - בודק התאמת view (או מעריך אותו אם לא ניתן).
    - בודק שנקודות החובה נראות עם conf ≥ thr.
    מחזיר (ok: bool, quality: float[0..1])
    """
    # View gating first: if view_mode is not provided, estimate it
    mode_current = (view_mode or "").lower()
    if not mode_current:
        try:
            mode_current, _ = estimate_view(kps, thr=thr)
            mode_current = (mode_current or "unknown").lower()
        except Exception:
            mode_current = "unknown"

    # Normalize and respect requested views unless "any"
    try:
        allowed_views = tuple(v.lower() for v in views) if views else ("any",)
    except Exception:
        allowed_views = ("any",)

    if allowed_views != ("any",) and mode_current not in allowed_views:
        return False, 0.0

    if not required:
        return True, 1.0

    confs = []
    for name in required:
        p = kps.get(name)
        if p is None:
            return False, 0.0
        try:
            if isinstance(p, (tuple, list)) and len(p) >= 3:
                conf = float(p[2])
            else:
                conf = float((p.get("conf", 0.0) if hasattr(p, "get") else 0.0) or 0.0)
        except Exception:
            conf = 0.0
        confs.append(conf)

    quality = sum(confs) / max(1, len(confs))
    if any(c < thr for c in confs):
        return False, float(quality)
    return True, float(quality)
