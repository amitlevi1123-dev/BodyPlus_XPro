# core/kinematics/metrics.py
# -------------------------------------------------------
# 📘 הסבר (לקריאה מהירה)
# הקובץ מחשב מדדי רוחב ויחסים בסיסיים מתוך נקודות שלד:
# 1) compute_widths_and_ratios:
#    - מחשב רוחב כתפיים (בפיקסלים) מתוך kps עם ספי נראות (thr=0.6).
#    - מחשב רוחב כפות רגליים (מרחק X בין הקרסוליים) ורוחב אחיזה (מרחק X בין שורשי כף היד).
#    - מחזיר גם יחס נורמליזציה לרוחב כתפיים: feet/shoulders, grip/shoulders.
# 2) feet_contact:
#    - מזהה מגע כף רגל עם הקרקע והרמת עקב באמצעות סף אנכי מנורמל לפי scale_px.
#    - לכל רגל מחזיר (contact, heel_lift).
# 3) weight_shift:
#    - מעריך העברת משקל לפי מיקום מרכז האגן מול מרכז בין העקבים (mid-feet).
#    - מחזיר "left"/"right"/"center"/"unknown" בהתאם לסטייה יחסית לרוחב כתפיים.
# 4) compute_head_metrics (חדש):
#    - מחזיר yaw/pitch/roll של הראש + confidence + ok על בסיס ears/eyes/nose/shoulders (2D).
#
# ⛓️ תלות ושמות נקודות:
# - משתמש ב-shoulders_width_px(kps, thr=0.6) מתוך core/visibility.
# - משתמש ב-center_point מתוך core/geometry.
# - גישה לנקודות פיקסלים (pixels) דרך העזר P(…, key) מתוך .pose_points.
#   דוגמאות מפתחות: "left_ankle", "right_ankle", "left_wrist", "right_wrist",
#                    "heel_left", "left_foot_index", "heel_right", "right_foot_index",
#                    "left_hip", "right_hip", "left_eye", "right_eye", "left_ear", "right_ear", "nose".
#
# 🧭 יחידות:
# - מרחקים: פיקסלים (2D מסך).
# - זוויות: מעלות.
# - יחסים: חסרי יחידות.
#
# 🛡️ יציבות:
# - פונקציות מחזירות None כאשר חסרות נקודות/מידע.
# - ספי ברירת מחדל שמרניים למניעת false positives.
# -------------------------------------------------------

from __future__ import annotations
from typing import Dict, Tuple, Optional

from ..visibility import shoulders_width_px as shoulders_w
from ..geometry import center_point
from .pose_points import P


_EPS = 1e-9


def _safe_div(n: Optional[float], d: Optional[float]) -> Optional[float]:
    """חלוקה בטוחה עם EPS; אם המונה/מחנה לא תקינים או המחנה קטן מדי → None."""
    try:
        if n is None or d is None:
            return None
        df = float(d)
        if not (df > _EPS):
            return None
        nf = float(n)
        return float(nf / df)
    except Exception:
        return None


def compute_widths_and_ratios(
    pixels: Dict[str, Optional[Tuple[float, float]]],
    kps: Dict[str, Tuple[float, float, float]],
) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    מחזיר: (shoulders_w_px, feet_w_px, grip_w_px, feet_over_shoulders, grip_over_shoulders)

    :param pixels: מילון נקודות בפיקסלים {name: (x,y)} (ללא confidence).
    :param kps:    מילון נקודות עם (x,y,conf) לחישוב רוחב כתפיים עם סף נראות.
    """
    sh_w = shoulders_w(kps, thr=0.6)

    ft_w = None
    if P(pixels, "left_ankle") and P(pixels, "right_ankle"):
        la, ra = P(pixels, "left_ankle"), P(pixels, "right_ankle")
        ft_w = float(abs(la[0] - ra[0]))

    grip_w = None
    if P(pixels, "left_wrist") and P(pixels, "right_wrist"):
        lw, rw = P(pixels, "left_wrist"), P(pixels, "right_wrist")
        grip_w = float(abs(lw[0] - rw[0]))

    feet_over = _safe_div(ft_w, sh_w)
    grip_over = _safe_div(grip_w, sh_w)

    return sh_w, ft_w, grip_w, feet_over, grip_over


def feet_contact(pixels: Dict[str, Optional[Tuple[float, float]]], scale_px: Optional[float]):
    """
    זיהוי מגע כף רגל/הרמת עקב:
      - contact: אם ההפרש האנכי heel-toe קטן מסף (thr_contact).
      - heel lift: אם העקב גבוה משמעותית מהאצבע.
    הסף מנורמל לפי scale_px (אם זמין); אחרת ברירת מחדל בפיקסלים.

    :param pixels: מילון נקודות בפיקסלים {name: (x,y)}.
    :param scale_px: גודל ייחוס לפיקסל (למשל רוחב כתפיים), לצורך נירמול סף.
    :return: (contact_left, contact_right, heel_lift_left, heel_lift_right)
    """
    def _contact_and_lift(heel_key, toe_key):
        heel = P(pixels, heel_key)
        toe = P(pixels, toe_key)
        if not heel or not toe:
            return None, None
        dy = abs(heel[1] - toe[1])
        thr_contact = (float(scale_px) * 0.05) if (scale_px is not None and float(scale_px) > _EPS) else 20.0
        contact = bool(dy < thr_contact)
        lift = bool(heel[1] < (toe[1] - (thr_contact * 0.5)))
        return contact, lift

    cl, ll = _contact_and_lift("heel_left", "left_foot_index")
    cr, lr = _contact_and_lift("heel_right", "right_foot_index")
    return cl, cr, ll, lr


def weight_shift(
    pixels: Dict[str, Optional[Tuple[float, float]]],
    sh_w: Optional[float],
) -> str:
    """
    הערכת העברת משקל לפי מיקום מרכז האגן מול מרכז בין העקבים (mid-feet).
    מחזיר: 'left' / 'right' / 'center' / 'unknown'
    """
    l_heel = P(pixels, "heel_left")
    r_heel = P(pixels, "heel_right")
    l_hip = P(pixels, "left_hip")
    r_hip = P(pixels, "right_hip")
    if not (l_heel and r_heel and l_hip and r_hip):
        return "unknown"
    hip_c = center_point(l_hip, r_hip)
    if hip_c is None:
        return "unknown"
    left_x = float(l_heel[0])
    right_x = float(r_heel[0])
    mid_feet = (left_x + right_x) / 2.0
    tol = (float(sh_w) * 0.04) if (sh_w is not None and float(sh_w) > _EPS) else 10.0
    if hip_c[0] < mid_feet - tol:
        return "left"
    if hip_c[0] > mid_feet + tol:
        return "right"
    return "center"


# ------------------------- Head/Neck metrics (חדש) -------------------------

def compute_head_metrics(
    pixels: Dict[str, Optional[Tuple[float, float]]],
    kps: Dict[str, Tuple[float, float, float]],
) -> Dict[str, object]:
    """
    מחזיר dict: {"yaw": float|None, "pitch": float|None, "roll": float|None,
                  "confidence": float, "ok": bool}
    לוגיקה יציבה 2D:
      - roll ~ שיפוע קו העיניים (right_eye - left_eye) מול אופק.
      - yaw  ~ היסט אופקי של מרכז אוזניים מול מרכז הכתפיים, מנורמל לרוחב כתפיים.
      - pitch ~ יחס אנכי של האף מול קו העיניים (שלילי = מבט למעלה).
    """
    import math

    def _slope_deg(a, b):
        if not a or not b:
            return None
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return None
        return math.degrees(math.atan2(dy, dx))

    L_ear, R_ear = P(pixels, "left_ear"), P(pixels, "right_ear")
    L_eye, R_eye = P(pixels, "left_eye"), P(pixels, "right_eye")
    nose        = P(pixels, "nose")
    L_sh, R_sh  = P(pixels, "left_shoulder"), P(pixels, "right_shoulder")

    # confidence משולב בסיסי: ממוצע visibility של נקודות הראש הזמינות
    conf_vals = []
    for name in ("left_ear","right_ear","left_eye","right_eye","nose"):
        v = kps.get(name)
        try:
            if isinstance(v, (tuple, list)) and len(v) >= 3:
                conf_vals.append(float(v[2]))
        except Exception:
            pass
    conf = float(sum(conf_vals)/len(conf_vals)) if conf_vals else 0.0

    # roll: שיפוע קו העיניים → הטיית ראש (הופכים סימן כדי להתאים לקונבנציה חיובית לימין)
    roll = _slope_deg(L_eye, R_eye)
    if roll is not None:
        roll = -float(roll)

    # yaw: מרכז אוזניים מול מרכז כתפיים, מנורמל לרוחב כתפיים
    yaw = None
    if L_ear and R_ear and L_sh and R_sh:
        shoulder_dx = abs(float(R_sh[0]) - float(L_sh[0])) + 1e-6
        ear_mid_x   = 0.5*(float(L_ear[0]) + float(R_ear[0]))
        sh_mid_x    = 0.5*(float(L_sh[0]) + float(R_sh[0]))
        yaw = 90.0 * float( (ear_mid_x - sh_mid_x) / shoulder_dx )
        yaw = max(-120.0, min(120.0, yaw))

    # pitch: האף מול קו העיניים (שלילי כאשר האף גבוה מהעיניים → מבט למעלה)
    pitch = None
    if nose and L_eye and R_eye:
        eye_y = 0.5*(float(L_eye[1]) + float(R_eye[1]))
        dy = float(nose[1]) - eye_y
        eye_dx = abs(float(R_eye[0]) - float(L_eye[0])) + 1e-6
        pitch = -60.0 * float(dy / eye_dx)
        pitch = max(-120.0, min(120.0, pitch))

    ok = any(v is not None for v in (yaw, pitch, roll))
    return {
        "yaw": yaw,
        "pitch": pitch,
        "roll": roll,
        "confidence": conf,
        "ok": bool(ok and conf > 0.2),
    }
