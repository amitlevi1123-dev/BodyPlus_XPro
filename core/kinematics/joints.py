# core/kinematics/joints.py
# -------------------------------------------------------
# Joints & Torso computations (stable build)
#
# מה יש כאן:
# - compute_joint_angles: זוויות ברך/ירך/קרסול/מרפק/כתף (במעלות 0..180).
# - compute_torso: טורסו חתום מול אנך/אופק + forward/flexion (signed).
# - compute_torso_forward_side_deg: זווית טורסו במבט צד (מוחלטת).
# - compute_spine_curvature_side: עיקום עמוד שדרה במבט צד.
# - compute_foot_and_alignment: זווית כף רגל ויישור ברך–רגל.
#
# עקרונות:
# - זוויות מפרקים הן 0..180 (לא חתומות, אין safe_deg עליהן).
# - מדדים חתומים מנורמלים ל-[−180, 180) באמצעות safe_deg.
# - החלקה ממוקדת למרפקים: Median-5 + round(..., 1).
# - שמות נקודות עקביים: left_* / right_*; עבור עקבים: heel_left / heel_right.
# -------------------------------------------------------


from __future__ import annotations
from typing import Dict, Optional, Tuple
from collections import deque

import numpy as np

from ..geometry import vec, angle_at, center_point, vector_vs_vertical, safe_deg
from .pose_points import P

# ---------------- Helpers ----------------

def _norm_deg(x: Optional[float]) -> Optional[float]:
    return None if x is None else safe_deg(x)

def _abs_or_none(x: Optional[float]) -> Optional[float]:
    return None if x is None else abs(x)

def _vec_safe(a, b) -> Optional[np.ndarray]:
    if a is None or b is None:
        return None
    return vec(a, b)

def angle_at_safe(a, b, c, signed: bool = False) -> Optional[float]:
    if a is None or b is None or c is None:
        return None
    ang = angle_at(a, b, c, signed=signed)
    return _norm_deg(ang) if signed else ang

def _round1(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), 1)
    except Exception:
        return None

# ---------------- Elbow smoothing: Median-5 + round(.,1) ----------------

_ELBOW_MED: Dict[str, deque] = {
    "elbow_left": deque(maxlen=5),
    "elbow_right": deque(maxlen=5),
}

def clear_elbow_smoothing_state():
    """Clear the elbow median filter state (for tests)"""
    _ELBOW_MED["elbow_left"].clear()
    _ELBOW_MED["elbow_right"].clear()

def _elbow_smooth(name: str, v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    try:
        q = _ELBOW_MED.get(name)
        if q is None:
            q = deque(maxlen=5)
            _ELBOW_MED[name] = q
        q.append(float(v))
        s = sorted(q)
        med = s[len(s) // 2]
        return _round1(med)
    except Exception:
        return _round1(v)

# ---------------- Main joint angles ----------------

def compute_joint_angles(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}

    # Knees (0..180)
    out["knee_left_deg"]  = angle_at_safe(P(pixels, "left_hip"),  P(pixels, "left_knee"),  P(pixels, "left_ankle"))
    out["knee_right_deg"] = angle_at_safe(P(pixels, "right_hip"), P(pixels, "right_knee"), P(pixels, "right_ankle"))

    # Hips (0..180)
    out["hip_left_deg"]   = angle_at_safe(P(pixels, "left_shoulder"),  P(pixels, "left_hip"),  P(pixels, "left_knee"))
    out["hip_right_deg"]  = angle_at_safe(P(pixels, "right_shoulder"), P(pixels, "right_hip"), P(pixels, "right_knee"))

    # Ankles (dorsiflexion) – knee–ankle–toe (0..180)
    out["ankle_dorsi_left_deg"]  = angle_at_safe(P(pixels, "left_knee"),  P(pixels, "left_ankle"),  P(pixels, "left_foot_index"))
    out["ankle_dorsi_right_deg"] = angle_at_safe(P(pixels, "right_knee"), P(pixels, "right_ankle"), P(pixels, "right_foot_index"))

    # Elbows (0..180) + smoothing
    elbow_left_deg  = angle_at(P(pixels,"left_shoulder"),  P(pixels,"left_elbow"),  P(pixels,"left_wrist"),  signed=False)
    elbow_right_deg = angle_at(P(pixels,"right_shoulder"), P(pixels,"right_elbow"), P(pixels,"right_wrist"), signed=False)
    out["elbow_left_deg"]  = _elbow_smooth("elbow_left",  elbow_left_deg)
    out["elbow_right_deg"] = _elbow_smooth("elbow_right", elbow_right_deg)

    # Shoulders (0..180)
    out["shoulder_left_deg"]  = angle_at_safe(P(pixels, "left_elbow"),  P(pixels, "left_shoulder"),  P(pixels, "left_hip"))
    out["shoulder_right_deg"] = angle_at_safe(P(pixels, "right_elbow"), P(pixels, "right_shoulder"), P(pixels, "right_hip"))

    return out

# ---------------- Torso (front/general) ----------------

def compute_torso(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    l_sh = P(pixels, "left_shoulder"); r_sh = P(pixels, "right_shoulder")
    l_hip = P(pixels, "left_hip");     r_hip = P(pixels, "right_hip")
    sh_c  = center_point(l_sh, r_sh) if l_sh and r_sh else None
    hip_c = center_point(l_hip, r_hip) if l_hip and r_hip else None
    torso_v = _vec_safe(hip_c, sh_c)
    if torso_v is None:
        out["torso_vs_vertical_deg"] = None
        out["torso_vs_horizontal_deg"] = None
        out["torso_forward_deg"] = None
        out["spine_flexion_deg"] = None
        return out
    v_deg = _norm_deg(vector_vs_vertical(torso_v, signed=True))
    out["torso_vs_vertical_deg"]   = v_deg
    out["torso_vs_horizontal_deg"] = _norm_deg(90.0 - (v_deg if v_deg is not None else 0.0)) if v_deg is not None else None
    out["torso_forward_deg"] = v_deg
    out["spine_flexion_deg"] = v_deg
    return out

# ---------------- Torso (side view) ----------------

def compute_torso_forward_side_deg(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Optional[float]:
    """
    Side-view torso angle vs vertical (absolute degrees).
    0 ~ upright; 30–45 ~ moderate squat; 60–90 ~ deep flexion.
    """
    l_sh = P(pixels, "left_shoulder"); r_sh = P(pixels, "right_shoulder")
    l_hip = P(pixels, "left_hip");     r_hip = P(pixels, "right_hip")
    sh_c  = center_point(l_sh, r_sh) if l_sh and r_sh else None
    hip_c = center_point(l_hip, r_hip) if l_hip and r_hip else None
    v = _vec_safe(hip_c, sh_c)
    if v is None:
        return None
    v_deg = vector_vs_vertical(v, signed=True)
    return _abs_or_none(_norm_deg(v_deg))

# ---------------- Spine curvature (side view) ----------------

def compute_spine_curvature_side(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Optional[float]:
    """
    Side-view spinal curvature (degrees): deviation from straight pelvis->shoulder->neck line.
    """
    l_sh = P(pixels, "left_shoulder"); r_sh = P(pixels, "right_shoulder")
    l_hip = P(pixels, "left_hip");     r_hip = P(pixels, "right_hip")
    sh_c  = center_point(l_sh, r_sh) if l_sh and r_sh else None
    hip_c = center_point(l_hip, r_hip) if l_hip and r_hip else None
    neck = P(pixels, "nose") or P(pixels, "left_ear") or P(pixels, "right_ear")
    if sh_c is None or hip_c is None or neck is None:
        return None
    theta = angle_at_safe(hip_c, sh_c, neck, signed=True)
    if theta is None:
        return None
    a = abs(theta)
    curvature_raw = min(a, abs(180.0 - a))
    curvature = max(0.0, curvature_raw - 5.0)
    return curvature

# ---------------- Feet angles & knee–foot alignment ----------------

def compute_foot_and_alignment(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {}
    foot_L = _vec_safe(P(pixels, "heel_left"),  P(pixels, "left_foot_index"))
    foot_R = _vec_safe(P(pixels, "heel_right"), P(pixels, "right_foot_index"))
    out["toe_angle_left_deg"]  = _norm_deg(vector_vs_vertical(foot_L, signed=True))  if foot_L is not None else None
    out["toe_angle_right_deg"] = _norm_deg(vector_vs_vertical(foot_R, signed=True))  if foot_R is not None else None
    thigh_L = _vec_safe(P(pixels, "left_hip"),  P(pixels, "left_knee"))
    thigh_R = _vec_safe(P(pixels, "right_hip"), P(pixels, "right_knee"))
    def _axis_signed(v): return _norm_deg(vector_vs_vertical(v, signed=True)) if v is not None else None
    thigh_L_v = _axis_signed(thigh_L); thigh_R_v = _axis_signed(thigh_R)
    foot_L_v  = _axis_signed(foot_L);  foot_R_v  = _axis_signed(foot_R)
    out["knee_foot_alignment_left_deg"]  = _norm_deg(thigh_L_v - foot_L_v) if (thigh_L_v is not None and foot_L_v is not None) else None
    out["knee_foot_alignment_right_deg"] = _norm_deg(thigh_R_v - foot_R_v) if (thigh_R_v is not None and foot_R_v is not None) else None
    return out