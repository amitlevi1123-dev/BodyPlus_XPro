# core/geometry.py
# -------------------------------------------------------
# 🧮 ג׳יאומטריה ומתמטיקה בסיסית למנוע ProCoach (גרסה מוקשחת ויציבה)
#
# מה כולל:
#  - המרות זווית: to_deg, wrap_deg, delta_deg, safe_deg
#  - נקודות/וקטורים: vec, center_point, distance
#  - וקטור מול אופק/אנך: vector_vs_horizontal, vector_vs_vertical
#  - זוויות בין קטעים: angle_at (כולל signed) + _angle_between_stable יציב
#  - נראות/סטטיסטיקה: average_visibility (מתעלם מ-NaN/Inf)
#  - ספי נירמול לפי סקייל: normalize_threshold
#  - עזרי וקטור: norm, unit, dot, cross2d, projection_len,
#    project_point_on_line, clamp, lerp
#
# עקרונות יציבות:
#  - הגנות על וקטור-אפס, חלוקה באפס, וערכים חריגים.
#  - חישוב זוויות עם atan2(|cross|, dot) (עמיד לרעש יותר מ-acos).
#  - עטיפת זוויות עקבית לטווח [-180, 180) (לא כולל 180).
#  - שימוש ב-fsum לממוצע וניקוי NaN/Inf.
#
# טופולוגיית צירים (Pixel Space):
#  - +x ימינה, +y מטה (כמו תמונה/מסך).
# -------------------------------------------------------

from __future__ import annotations
from typing import Optional, Tuple, Iterable
import math
import numpy as np

__all__ = [
    # זוויות
    "to_deg", "wrap_deg", "delta_deg", "safe_deg",
    # נקודות/וקטורים בסיסיים
    "vec", "center_point", "distance",
    # זוויות בין וקטורים וקטעי קו
    "vector_vs_horizontal", "vector_vs_vertical",
    "angle_at",
    # נראות/סקייל
    "average_visibility", "normalize_threshold",
    # עזרי וקטור נוספים
    "norm", "unit", "dot", "cross2d",
    "projection_len", "project_point_on_line",
    "clamp", "lerp",
    # (אופציונלי לחשיפה פנימית/בדיקות)
    "_angle_between_stable",
]

# קבועי יציבות נומרית (מיושר להמלצה)
_EPS = 1e-9

# -------------------------- המרות זווית --------------------------

def to_deg(rad: float) -> float:
    """המרת רדיאנים למעלות."""
    return float(rad) * 180.0 / math.pi


def _normalize_angle_deg(x: float) -> float:
    """
    נרמול זווית למעלות בטווח [-180, 180).
    שים לב: 180 לא יוחזר אף פעם — יהפוך ל- -180.
    """
    y = (float(x) + 180.0) % 360.0 - 180.0
    # עקביות: אם התקבל 180 בגלל רעש מספרי, נחזיר -180
    return -180.0 if abs(y - 180.0) < 1e-9 else y


def safe_deg(x: Optional[float]) -> Optional[float]:
    """
    ניקוי ונרמול זווית:
    - אם x None/NaN/Inf → מחזיר None
    - אחרת: מחזיר זווית בטווח [-180, 180)
    הערה: לא מיועד ל-0..180 של מפרקים, אלא למדדים חתומים.
    """
    if x is None:
        return None
    try:
        xf = float(x)
        if not math.isfinite(xf):
            return None
        return _normalize_angle_deg(xf)
    except Exception:
        return None


def wrap_deg(x: float, lo: float = -180.0, hi: float = 180.0) -> float:
    """עטיפת זווית לטווח [lo, hi). ברירת מחדל: [-180, 180)."""
    lo_f, hi_f = float(lo), float(hi)
    rng = hi_f - lo_f
    if not math.isfinite(rng) or abs(rng) < _EPS:
        return float(x)
    y = ((float(x) - lo_f) % rng) + lo_f
    # מניעת החזרה של hi בדיוק
    return lo_f if abs(y - hi_f) < 1e-9 else y


def delta_deg(a: float, b: float) -> float:
    """
    הפער הקצר ביותר בין שתי זוויות: a - b, עטוף לטווח [-180, 180).
    שימושי להבדלי זוויות לאורך זמן (sweep).
    """
    return _normalize_angle_deg(float(a) - float(b))


# -------------------------- נקודות ווקטורים --------------------------

def vec(a: Tuple[float, float], b: Tuple[float, float]) -> np.ndarray:
    """וקטור דו־ממדי בין שתי נקודות (בפיקסלים): b - a."""
    return np.array([float(b[0]) - float(a[0]), float(b[1]) - float(a[1])], dtype=float)


def center_point(a: Optional[Tuple[float, float]],
                 b: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """נקודת מרכז בין שתי נקודות, או None אם אחת חסרה."""
    if a is None or b is None:
        return None
    return ((float(a[0]) + float(b[0])) * 0.5, (float(a[1]) + float(b[1])) * 0.5)


def distance(a: Optional[Tuple[float, float]],
             b: Optional[Tuple[float, float]]) -> Optional[float]:
    """מרחק אוקלידי בין שתי נקודות (פיקסלים) או None אם חסר."""
    if a is None or b is None:
        return None
    dx = float(b[0]) - float(a[0])
    dy = float(b[1]) - float(a[1])
    return float(math.hypot(dx, dy))


# -------------------------- עזרי וקטור כלליים --------------------------

def norm(v: np.ndarray) -> float:
    """אורך וקטור (np.linalg.norm) עם הגנה לחריגות/אפס."""
    try:
        n = float(np.linalg.norm(v))
        return 0.0 if (not math.isfinite(n) or n < _EPS) else n
    except Exception:
        return 0.0


def unit(v: np.ndarray) -> np.ndarray:
    """וקטור יחידה (אם אורך אפס → [0,0])."""
    n = norm(v)
    if n == 0.0:
        return np.array([0.0, 0.0], dtype=float)
    return np.array([float(v[0]) / n, float(v[1]) / n], dtype=float)


def dot(u: np.ndarray, v: np.ndarray) -> float:
    """מכפלה סקלרית."""
    try:
        d = float(np.dot(u, v))
        return 0.0 if not math.isfinite(d) else d
    except Exception:
        return 0.0


def cross2d(u: np.ndarray, v: np.ndarray) -> float:
    """
    מכפלה וקטורית ב-2D (רכיב z של u×v).
    שימושי לזיהוי כיוון סיבוב/סימן זווית.
    """
    try:
        cz = float(u[0] * v[1] - u[1] * v[0])
        return 0.0 if not math.isfinite(cz) else cz
    except Exception:
        return 0.0


def projection_len(u: np.ndarray, v_dir: np.ndarray) -> float:
    """אורך ההיטל של u על כיוון v_dir (מנרמל v_dir בפנים)."""
    d = unit(v_dir)
    return dot(u, d)


def project_point_on_line(p: Tuple[float, float],
                          a: Tuple[float, float],
                          b: Tuple[float, float]) -> Tuple[float, float]:
    """
    היטל הנקודה p על הישר העובר דרך a→b.
    אם a=b (קטע אפס) → מחזיר a.
    """
    ab = vec(a, b)
    ab_n = norm(ab)
    if ab_n == 0.0:
        return (float(a[0]), float(a[1]))
    ap = vec(a, p)
    t = dot(ap, ab) / (ab_n * ab_n)  # denom>0 כי ab_n>0
    proj = np.array([a[0], a[1]], dtype=float) + t * ab
    return (float(proj[0]), float(proj[1]))


def clamp(x: float, lo: float, hi: float) -> float:
    """הצמדה לטווח [lo, hi] (מתקן אם lo>hi). בטוח ל-NaN/Inf."""
    lo_f, hi_f = float(lo), float(hi)
    if lo_f > hi_f:
        lo_f, hi_f = hi_f, lo_f
    xf = float(x)
    if not math.isfinite(xf):
        if math.isnan(xf):
            return (lo_f + hi_f) * 0.5
        return lo_f if xf < 0 else hi_f
    return float(min(max(xf, lo_f), hi_f))


def lerp(a: float, b: float, t: float) -> float:
    """Interpolate ליניארי בין a ל-b לפי t∈[0,1]."""
    return float(a) + float(t) * (float(b) - float(a))


# -------------------------- זוויות בין וקטורים/קטעים --------------------------

def _angle_between_stable(u: np.ndarray, v: np.ndarray, signed: bool = False) -> Optional[float]:
    """
    זווית בין שני וקטורים (מעלות) עם יציבות גבוהה:
    - signed=False  → מחזיר זווית פנימית בטווח [0..180]
    - signed=True   → מחזיר בטווח [-180, 180)
    משתמשים ב-atan2(|cross|, dot) (או atan2(cross, dot) לחתומה).
    """
    nu = float(np.linalg.norm(u)); nv = float(np.linalg.norm(v))
    if nu == 0.0 or nv == 0.0:
        return None  # zero-length guard
    uu = u/nu; vv = v/nv
    dotv = float(np.dot(uu, vv)); dotv = max(-1.0, min(1.0, dotv))
    cross = float(uu[0]*vv[1] - uu[1]*vv[0])

    if signed:
        ang = math.degrees(math.atan2(cross, dotv))
        return ((ang + 180.0) % 360.0) - 180.0
    ang = math.degrees(math.atan2(abs(cross), dotv))  # unsigned 0..180
    ang = max(0.0, min(180.0, ang))                   # simple clamp
    return ang


# angle_at: explicit BA=A−B, BC=C−B (NumPy), no vec()
def angle_at(a, b, c, signed: bool = False):
    if a is None or b is None or c is None:
        return None
    BA = np.array([a[0]-b[0], a[1]-b[1]], dtype=float)
    BC = np.array([c[0]-b[0], c[1]-b[1]], dtype=float)
    return _angle_between_stable(BA, BC, signed=signed)


# -------------------------- וקטור מול אנך/אופק --------------------------
# מערכת פיקסלים: x ימינה, y מטה. אופק = ציר x, אנך = ציר y.

def _is_zero_vec(v: np.ndarray) -> bool:
    try:
        return abs(float(v[0])) < _EPS and abs(float(v[1])) < _EPS
    except Exception:
        return True


def vector_vs_horizontal(v: np.ndarray, signed: bool = True) -> float:
    """
    זווית הווקטור מול האופק (ציר x).
    signed=True  → [-180, 180)
    signed=False → [0, 180]
    """
    if v is None or _is_zero_vec(v):
        return 0.0
    ang = to_deg(math.atan2(float(v[1]), float(v[0])))
    return clamp(abs(ang), 0.0, 180.0) if not signed else float(_normalize_angle_deg(ang))


def vector_vs_vertical(v: np.ndarray, signed: bool = True) -> float:
    """
    זווית הווקטור מול האנך (ציר y).
    signed=True  → [-180, 180) כאשר 0° = אנך מוחלט
    signed=False → [0, 180]
    נגזר מ-90° - זווית מול האופק.
    """
    if v is None or _is_zero_vec(v):
        return 0.0
    ang_h = to_deg(math.atan2(float(v[1]), float(v[0])))
    ang_v = _normalize_angle_deg(90.0 - ang_h)
    return clamp(abs(ang_v), 0.0, 180.0) if not signed else float(ang_v)


# -------------------------- נראוּת ממוצעת --------------------------

def average_visibility(values: Iterable[float]) -> float:
    """
    ממוצע נראות (0..1). אם הרשימה ריקה – 0.0.
    מתעלם מ-NaN/Inf כדי לא לזהם ממוצע; אם הכל לא תקין → 0.0.
    """
    clean: list[float] = []
    for v in values:
        try:
            vf = float(v)
            if math.isfinite(vf):
                clean.append(vf)
        except Exception:
            continue
    if not clean:
        return 0.0
    return float(math.fsum(clean) / len(clean))


# -------------------------- עזרי סקייל --------------------------

def normalize_threshold(px: float,
                        scale_px: Optional[float],
                        k: Optional[float] = None) -> float:
    """
    המרת סף לפיקסלים בהתאם לסקייל:
    - אם k סופק ויש scale_px חיובי → סף יחסי: k * scale_px
    - אחרת → חוזר ל-px (סף מוחלט)
    """
    if k is not None and scale_px and float(scale_px) > _EPS:
        return float(k) * float(scale_px)
    return float(px)
