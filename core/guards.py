# core/guards.py
# -------------------------------------------------------
# 🛡️ Guards & Sanity checks למנוע ProCoach
#
# מטרות:
# 1) למנוע ערכים לא תקינים (NaN, אינסוף).
# 2) להחזיר None במקום ערכים לא הגיוניים → שלא יתחרבש החישוב / הציון.
# 3) להבדיל בין סוגי מפרקים:
#    - מפרקי גוף (ברך, ירך, כתף, מרפק): טווח פיזי סביר [0..200°].
#    - מפרקי שורש־כף־יד: טווחים רחבים יותר, כולל זוויות שליליות יחסיות
#      → נניח טווח [-180..180°] כדי לשמר תנועות כפיפה/סטייה.
#    - פרונציה/סופינציה של כף היד: קטגוריה דיסקרטית (לא כאן).
# 4) הרחבות: ראש/צוואר (Yaw/Pitch/Roll), קונפידנס, פיקסלים/נקודות, מהירות/תאוצה,
#    סקיילים חיוביים ויחסים מותאמים.
# -------------------------------------------------------

from __future__ import annotations
from typing import Optional, Tuple
import math

__all__ = [
    # בסיס
    "is_finite_number", "guard_number", "guard_in_range",
    # זוויות וכלים
    "normalize_signed_angle", "normalize_abs_angle",
    "guard_joint_angle_deg", "guard_wrist_angle_deg", "guard_signed_angle_deg",
    # יחסים/סקיילים
    "guard_ratio", "guard_ratio_custom", "guard_positive_scale",
    # הסתברויות/בוליאני
    "clamp01", "guard_confidence", "guard_probability", "guard_bool",
    # פיקסלים/נקודות
    "guard_px", "guard_point2d",
    # דינמיקה
    "guard_velocity_deg_s", "guard_accel_deg_s2",
    # אי-שלילי ושלם
    "guard_nonneg", "guard_uint",
    # ראש/צוואר
    "guard_head_signed_angle_deg",
    "guard_head_yaw_deg", "guard_head_pitch_deg", "guard_head_roll_deg",
    "guard_neck_flexion_ext_deg", "guard_neck_lateral_bend_deg", "guard_neck_rotation_deg",
    "guard_head_pose",
]

# סובלנות קטנה לחישובי ציפה
EPS = 1e-6

# -------- בדיקות בסיס --------

def is_finite_number(x: object) -> bool:
    """True אם x הוא מספר סופי (int/float)."""
    return isinstance(x, (int, float)) and math.isfinite(float(x))

def guard_number(x: Optional[float]) -> Optional[float]:
    """מחזיר x אם הוא מספר סופי; אחרת None."""
    if x is None:
        return None
    try:
        xf = float(x)
    except Exception:
        return None
    return xf if math.isfinite(xf) else None

def guard_in_range(x: Optional[float], lo: float, hi: float, eps: float = EPS) -> Optional[float]:
    """
    בודק טווח באופן סלחני (עם EPS) כדי להימנע מהשלכות ציפה.
    מחזיר None אם מחוץ לטווח; אחרת את הערך המקורי (עם קלמפ עדין בקצוות).
    """
    x = guard_number(x)
    if x is None:
        return None
    if x < lo - eps or x > hi + eps:
        return None
    if abs(x - lo) <= eps:
        return lo
    if abs(x - hi) <= eps:
        return hi
    return x

# -------- עזרי נורמליזציה לזוויות (לא בשימוש אוטומטי) --------

def normalize_signed_angle(x: float) -> float:
    """ממפה לטווח [-180, 180]."""
    x = (x + 180.0) % 360.0 - 180.0
    if x == -180.0:
        x = 180.0
    return x

def normalize_abs_angle(x: float) -> float:
    """ממפה לטווח [0, 180] מזווית כלשהי (כולל חתומה)."""
    xs = normalize_signed_angle(x)
    return abs(xs)

# -------- מפרקי גוף --------

def guard_joint_angle_deg(x: Optional[float], lo: float = 0.0, hi: float = 200.0) -> Optional[float]:
    """זוויות מפרקי גוף (ברך/ירך/מרפק/כתף): ~0–200°."""
    return guard_in_range(x, lo, hi)

# -------- מפרקי שורש־כף־יד --------

def guard_wrist_angle_deg(x: Optional[float], lo: float = -180.0, hi: float = 180.0) -> Optional[float]:
    """זוויות יחסיות בשורש־כף־היד (flexion/extension, radial/ulnar): [-180..180]."""
    return guard_in_range(x, lo, hi)

# -------- זוויות חתומות כלליות --------

def guard_signed_angle_deg(x: Optional[float], lo: float = -180.0, hi: float = 180.0) -> Optional[float]:
    """זוויות חתומות מול צירים (Torso מול אנך/אופק): [-180..180]."""
    return guard_in_range(x, lo, hi)

# -------- יחסים (Ratios) --------

def guard_ratio(x: Optional[float], lo: float = 0.0, hi: float = 10.0) -> Optional[float]:
    """יחסים חיוביים (feet/shoulders, grip/shoulders וכו') עם תקרה 10."""
    return guard_in_range(x, lo, hi)

# ===================== הרחבות (לשימוש אופציונלי) =====================

# --- Head & Neck angles (Yaw / Pitch / Roll) ---

def guard_head_signed_angle_deg(x: Optional[float], lo: float = -120.0, hi: float = 120.0) -> Optional[float]:
    """
    זוויות ראש/צוואר (Yaw/Pitch/Roll). טווח מעט צר מהכללי כדי לבלום קפיצות.
    """
    return guard_in_range(x, lo, hi)

def guard_head_yaw_deg(x: Optional[float]) -> Optional[float]:
    """Yaw (שמאל/ימין): טווח טיפוסי ~[-90..90], עם מרווח בטיחות."""
    return guard_in_range(x, -110.0, 110.0)

def guard_head_pitch_deg(x: Optional[float]) -> Optional[float]:
    """Pitch (למעלה/למטה): טווח טיפוסי ~[-60..60], עם מרווח בטיחות."""
    return guard_in_range(x, -80.0, 80.0)

def guard_head_roll_deg(x: Optional[float]) -> Optional[float]:
    """Roll (אוזן-לכתף): טווח טיפוסי ~[-45..45], עם מרווח בטיחות."""
    return guard_in_range(x, -70.0, 70.0)

def guard_neck_flexion_ext_deg(x: Optional[float]) -> Optional[float]:
    """צוואר כפיפה/פשיטה: לרוב קטן מטווח הראש הכולל."""
    return guard_in_range(x, -60.0, 60.0)

def guard_neck_lateral_bend_deg(x: Optional[float]) -> Optional[float]:
    """צוואר כפיפה צידית."""
    return guard_in_range(x, -45.0, 45.0)

def guard_neck_rotation_deg(x: Optional[float]) -> Optional[float]:
    """צוואר רוטציה (שמאל/ימין)."""
    return guard_in_range(x, -80.0, 80.0)

def guard_head_pose(pose: Optional[dict]) -> Optional[dict]:
    """
    ניקוי "פוזת ראש" כמילון {"yaw":..,"pitch":..,"roll":..,"confidence":..}.
    מחזיר מילון נקי או None אם שלושת הצירים לא תקינים.
    """
    if not isinstance(pose, dict):
        return None
    y = guard_head_yaw_deg(pose.get("yaw"))
    p = guard_head_pitch_deg(pose.get("pitch"))
    r = guard_head_roll_deg(pose.get("roll"))
    c = guard_confidence(pose.get("confidence"))
    if y is None and p is None and r is None:
        return None
    return {"yaw": y, "pitch": p, "roll": r, "confidence": c}

# --- Confidence / Probability ---

def clamp01(x: Optional[float]) -> Optional[float]:
    """גזירה לטווח [0..1] אם מספר; אחרת None."""
    x = guard_number(x)
    if x is None:
        return None
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x

def guard_confidence(x: Optional[float]) -> Optional[float]:
    """קונפידנס/וויזיביליטי לטווח [0..1] או None."""
    return clamp01(x)

def guard_probability(x: Optional[float]) -> Optional[float]:
    """Alias ל-guard_confidence (נוח כששמות הם prob/probability)."""
    return guard_confidence(x)

# --- Booleans ---

def guard_bool(x: object) -> Optional[bool]:
    """ממיר ל-True/False אם אפשר; אחרת None."""
    try:
        if isinstance(x, bool):
            return x
        if isinstance(x, (int, float)) and math.isfinite(float(x)):
            return bool(x)
        return None
    except Exception:
        return None

# --- Pixels & Points ---

def guard_px(x: Optional[float], lo: float = -1e6, hi: float = 1e6) -> Optional[float]:
    """ערך פיקסל סופי ובטווח רחב (שימושי לדלטות בפיקסלים)."""
    return guard_in_range(x, lo, hi)

def guard_point2d(p: Optional[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """(x,y) אם שני הערכים מספריים סופיים; אחרת None."""
    if p is None or not isinstance(p, (tuple, list)) or len(p) < 2:
        return None
    x = guard_px(p[0])
    y = guard_px(p[1])
    if x is None or y is None:
        return None
    return (x, y)

# --- Velocities / Accelerations (deg/s, deg/s^2) ---

def guard_velocity_deg_s(x: Optional[float], lo: float = -1000.0, hi: float = 1000.0) -> Optional[float]:
    """מהירות זוויתית בטווח סביר."""
    return guard_in_range(x, lo, hi)

def guard_accel_deg_s2(x: Optional[float], lo: float = -5000.0, hi: float = 5000.0) -> Optional[float]:
    """תאוצה זוויתית בטווח סביר."""
    return guard_in_range(x, lo, hi)

# --- Scales / Non-negative / UInt ---

def guard_positive_scale(x: Optional[float], hi: float = 1e6) -> Optional[float]:
    """סקיילים חיוביים (למשל רוחב כתפיים בפיקסלים)."""
    return guard_in_range(x, 0.0, hi)

def guard_nonneg(x: Optional[float], hi: float = 1e12) -> Optional[float]:
    """מספר אי-שלילי (≥0)."""
    return guard_in_range(x, 0.0, hi)

def guard_uint(x: Optional[float], hi: float = 1e12) -> Optional[int]:
    """מונה שלם אי-שלילי; אחרת None."""
    xv = guard_nonneg(x, hi=hi)
    if xv is None:
        return None
    try:
        return int(xv)
    except Exception:
        return None

# --- Ratios with custom upper bound ---

def guard_ratio_custom(x: Optional[float], hi: float = 10.0) -> Optional[float]:
    """יחס חיובי עד תקרה מותאמת."""
    return guard_in_range(x, 0.0, hi)
