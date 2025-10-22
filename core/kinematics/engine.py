# core/kinematics/engine.py
# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🧠 KinematicsComputer – מנוע חישוב קינמטיקה
# - אחראי להריץ Pose/Hands → לחשב מדדים → להחזיר payload
# - משתמש ב־geometry / visibility / signals / guards
# - מחלק חישובים לתת־מודולים (pose_points, joints, hands, metrics)
# - מוסיף פילטרים טמפורליים, Jitter, Guards, Gating (compute_if_visible), ו־LKG
# - כולל: spine_curvature_side + torso_forward_side_deg (מדדי צד)
# - Gate/EMA דינמי/Outlier/Deadband מ-core/filters_config.py
# - חדש: מדדי ראש (head_yaw/pitch/roll + confidence/ok) עם גארדים ייעודיים
# -------------------------------------------------------

from __future__ import annotations
import os
from typing import Dict, Tuple, Optional, List
from collections import deque

from ..geometry import average_visibility
from ..signals import TemporalFilter, JitterMeter, LKGBuffer, HysteresisBool, now_ms
from ..visibility import compute_if_visible, estimate_view, compute_visibility_gate
from ..guards import (
    guard_joint_angle_deg, guard_signed_angle_deg, guard_number, guard_ratio,
    guard_head_signed_angle_deg, guard_confidence
)
from .pose_points import collect_pose_pixels, visibility_list, optional_pose2d, kps_from_pose, P
from .joints import (
    compute_joint_angles,
    compute_torso,
    compute_foot_and_alignment,
    compute_spine_curvature_side,
    compute_torso_forward_side_deg,
)
from .hands import grip_state_from_hands, wrist_angles, hand_orientation, he
from .metrics import compute_widths_and_ratios, feet_contact, weight_shift, compute_head_metrics

# === פילטרים/קונפיג ===
from ..filters_config import CONFIG, alpha_from_conf, is_outlier, metric_deadband, ui_color_for_conf

# === Payload Integration (v1.2.0) ===
try:
    from ..payload import Payload, from_kinematics_output
    _PAYLOAD_AVAILABLE = True
except ImportError:
    _PAYLOAD_AVAILABLE = False
    Payload = None  # type: ignore
    from_kinematics_output = None  # type: ignore

# Toggle for new payload format (environment variable)
USE_NEW_PAYLOAD = os.getenv("USE_NEW_PAYLOAD", "0") == "1"

# ---------------- Stable schema & gating maps (additive; keep flat keys) ----------------
PAYLOAD_VERSION = "1.2.0"  # ↑ עודכן לתמיכה ב-Payload החדש

# >>> ADDED: נתיב מודול + הדפסה חד-משמעית על טעינה
MODULE_PATH = os.path.abspath(__file__)
print(f"[KINEMATICS] loaded from: {MODULE_PATH}  | PAYLOAD_VERSION={PAYLOAD_VERSION}")

SCHEMA_KEYS = [
    # torso & spine
    "torso_forward_deg", "torso_vs_vertical_deg", "torso_vs_horizontal_deg",
    "spine_flexion_deg",
    "torso_forward_side_deg",
    "spine_curvature_side_deg",
    "spine_curvature_side_vel_deg_s",
    "spine_curvature_side_acc_deg_s2",
    # joints
    "knee_left_deg", "knee_right_deg", "hip_left_deg", "hip_right_deg",
    "shoulder_left_deg", "shoulder_right_deg",
    "elbow_left_deg", "elbow_right_deg",
    "ankle_dorsi_left_deg", "ankle_dorsi_right_deg",
    # feet & alignment
    "toe_angle_left_deg", "toe_angle_right_deg",
    "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
    "foot_contact_left", "foot_contact_right", "heel_lift_left", "heel_lift_right",
    "weight_shift",
    # widths & ratios
    "shoulders_width_px", "feet_width_px", "grip_width_px",
    "feet_w_over_shoulders_w", "grip_w_over_shoulders_w",
    # symmetry
    "knee_delta_deg", "hip_delta_deg", "shoulders_delta_px", "hips_delta_px",
    # hands
    "wrist_flex_ext_left_deg", "wrist_flex_ext_right_deg",
    "wrist_radial_ulnar_left_deg", "wrist_radial_ulnar_right_deg",
    "grip_state_left", "grip_state_right",
    "hand_orientation_left", "hand_orientation_right",
    "hand_orientation_left_he", "hand_orientation_right_he",
    # head (flat)
    "head_yaw_deg", "head_pitch_deg", "head_roll_deg",
    "head_confidence", "head_ok",
    # temporal/jitter debug
    "torso_forward_vel_deg_s", "torso_forward_acc_deg_s2",
    "torso_forward_side_jitter_std", "spine_curvature_side_jitter_std",
    "dt_ms",
    # (רשות) קטגוריית צבע ל-UI
    "ui.conf_category",
]


def empty_payload():
    d = {k: None for k in SCHEMA_KEYS}
    d.update({
        "view_mode": "unknown", "view_score": 0.0,
        "average_visibility": 0.0, "visible_points_count": 0,
        "confidence": 0.0, "quality_score": 0.0, "low_confidence": True,
        "frame.w": 0, "frame.h": 0,
        "frame": {"w": 0, "h": 0},
        "meta": {
            "payload_version": PAYLOAD_VERSION, "frame_id": 0, "fps_est": 0.0,
            "detected": False, "valid": False, "updated_at_ms": 0, "age_ms": 0,
        },
        "meta.detected": False, "meta.updated_at": 0, "meta.age_ms": 0,
        "pose2d": None,
    })
    return d


def fill_schema(partial: dict) -> dict:
    base = empty_payload()
    base.update(partial or {})
    return base


# --- Gating requirements (only for metrics needing explicit gates) ---
REQS = {
    # side-only metrics
    "torso_forward_side_deg": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    "spine_curvature_side_deg": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    "spine_curvature_side_vel_deg_s": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    "spine_curvature_side_acc_deg_s2": ["left_shoulder", "right_shoulder", "left_hip", "right_hip"],
    # feet/alignment
    "toe_angle_left_deg": ["left_heel", "left_foot_index"],
    "toe_angle_right_deg": ["right_heel", "right_foot_index"],
    "knee_foot_alignment_left_deg": ["left_hip", "left_knee", "left_ankle", "left_heel", "left_foot_index"],
    "knee_foot_alignment_right_deg": ["right_hip", "right_knee", "right_ankle", "right_heel", "right_foot_index"],
    # symmetry px
    "shoulders_delta_px": ["left_shoulder", "right_shoulder"],
    "hips_delta_px": ["left_hip", "right_hip"],
}
VIEWS = {
    "torso_forward_side_deg": ("side",),
    "spine_curvature_side_deg": ("side",),
    "spine_curvature_side_vel_deg_s": ("side",),
    "spine_curvature_side_acc_deg_s2": ("side",),
    "toe_angle_left_deg": ("front", "back"),
    "toe_angle_right_deg": ("front", "back"),
    "knee_foot_alignment_left_deg": ("front", "back"),
    "knee_foot_alignment_right_deg": ("front", "back"),
    "shoulders_delta_px": ("front", "back"),
    "hips_delta_px": ("front", "back"),
}


def gate_metric(key: str, kps: dict, view_mode: str, value, thr: float = 0.6):
    reqs = REQS.get(key, [])
    allowed = VIEWS.get(key, ("any",))
    ok, _q = compute_visibility_gate(kps, reqs, thr=thr, views=allowed, view_mode=view_mode)
    return value if ok else None


class KinematicsComputer:
    """Kinematics engine with temporal smoothing, jitter, LKG fallback, and full filter stack."""

    def __init__(self):
        p = CONFIG.profile  # קיצור

        # --- פילטרים טמפורליים (EMA דינמי לפי conf) ---
        dyn = (lambda c: alpha_from_conf(c, p.ema))
        self.filters = {
            # מפרקים (זוויות 0..180° → EMA רגיל, לא מחזורי)
            "knee_left": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "knee_right": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "hip_left": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "hip_right": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "shoulder_left": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "shoulder_right": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "elbow_left": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "elbow_right": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),

            # מדדים חתומים/צידיים
            "torso_forward": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "torso_forward_side": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
            "spine_curvature_side": TemporalFilter(alpha=p.ema.alpha_max, dynamic_alpha_fn=dyn),
        }

        # --- JitterMeters (לפי קונפיג) ---
        self.jitter = {
            "knee_left": JitterMeter(window_ms=p.jitter.window_ms),
            "knee_right": JitterMeter(window_ms=p.jitter.window_ms),
            "hip_left": JitterMeter(window_ms=p.jitter.window_ms),
            "hip_right": JitterMeter(window_ms=p.jitter.window_ms),
            "shoulder_left": JitterMeter(window_ms=p.jitter.window_ms),
            "shoulder_right": JitterMeter(window_ms=p.jitter.window_ms),
            "torso_forward": JitterMeter(window_ms=p.jitter.window_ms),
            "torso_forward_side": JitterMeter(window_ms=p.jitter.window_ms),
            "spine_curvature_side": JitterMeter(window_ms=p.jitter.window_ms),
        }

        # --- LKG בהתאם לפרופיל ---
        self.lkg = LKGBuffer(
            enabled=p.lkg.enabled,
            max_age_ms=p.lkg.max_age_ms,
            min_conf_for_store=p.lkg.min_conf_for_store
        )

        # --- Hysteresis (כולל min_hold_ms) ---
        self.foot_contact_left_hys = HysteresisBool(th_on=p.hyst.on_thr, th_off=p.hyst.off_thr, initial=False, min_hold_ms=p.hyst.min_hold_ms)
        self.foot_contact_right_hys = HysteresisBool(th_on=p.hyst.on_thr, th_off=p.hyst.off_thr, initial=False, min_hold_ms=p.hyst.min_hold_ms)
        self.heel_lift_left_hys = HysteresisBool(th_on=p.hyst.on_thr, th_off=p.hyst.off_thr, initial=False, min_hold_ms=p.hyst.min_hold_ms)
        self.heel_lift_right_hys = HysteresisBool(th_on=p.hyst.on_thr, th_off=p.hyst.off_thr, initial=False, min_hold_ms=p.hyst.min_hold_ms)

        # --- זיכרון ל-Outlier/Deadband ---
        self._last_raw: Dict[str, Optional[float]] = {}
        self._last_smooth: Dict[str, Optional[float]] = {}

        # --- באפרים ממוחזרים להפחתת הקצאות ---
        self._payload_raw: Dict[str, object] = {}
        self._gated: Dict[str, object] = {}
        self._nested_meta: Dict[str, object] = {}
        self._nested_frame: Dict[str, int] = {}

        # --- החלקת Median-3 + עיגול ספרה אחת (מפתח→deque) ---
        self._median_buf: Dict[str, deque] = {}

        self._frame_id = 0

    @staticmethod
    def _delta_deg_simple(a: Optional[float], b: Optional[float]) -> Optional[float]:
        """הפרש חתום בין זוויות בטווח [-180, 180)."""
        if a is None or b is None:
            return None
        try:
            d = float(a) - float(b)
            if abs(d) > 180.0:
                d = ((d + 180.0) % 360.0) - 180.0
            return float(d)
        except Exception:
            return None

    # ---------------------------- עזר פנימי למסננים ----------------------------

    def _round1(self, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        try:
            return round(float(v), 1)
        except Exception:
            return None

    def _median3_round1(self, key: str, v: Optional[float]) -> Optional[float]:
        """Median-3 + עיגול ספרה אחת. מייצב ~0.2–0.4° ללא פגיעה ברספונס."""
        if v is None:
            return None
        try:
            q = self._median_buf.get(key)
            if q is None:
                q = deque(maxlen=3)
                self._median_buf[key] = q
            q.append(float(v))
            s = sorted(q)
            med = s[len(s) // 2]
            return round(med, 1)
        except Exception:
            return self._round1(v)

    def _apply_filters(self, key: str, kind: str, x: Optional[float], conf: float, shoulder_w_px: Optional[float]) -> Optional[float]:
        """
        מסנן ערך יחיד לפי: Gate קונפידנס כללי → Outlier (Δ raw) → EMA דינמי → Deadband (על y) → החזרה.
        kind ∈ {"angle","px","ratio"}
        """
        if os.getenv("PROCOACH_TEST_MODE") == "1":
            if x is not None:
                return round(float(x), 1)
            return None

        p = CONFIG.profile

        # 0) Gate כללי לפי קונפידנס
        if conf < p.visibility.conf_thr:
            return None

        # 1) Outlier על Δ raw (אם יש דגימה קודמת)
        last_raw = self._last_raw.get(key)
        if x is not None and last_raw is not None:
            delta = float(x) - float(last_raw)
            if is_outlier(delta, kind, p.outlier, shoulder_width_px=shoulder_w_px):
                x = None

        # עדכון last_raw
        if x is not None:
            self._last_raw[key] = float(x)

        # 2) EMA דינמי
        filt = self.filters.get(key)
        if filt is None:
            y, _, _, _ = None, None, None, 0
        else:
            y, _, _, _ = filt.update(x, conf=conf)

        # 3) Deadband על ה-output המוחלק מול last_smooth
        if y is not None:
            last_s = self._last_smooth.get(key)
            if last_s is not None:
                y = metric_deadband(y, last_s, kind, p.deadband)
            self._last_smooth[key] = y

        # 4) Median-3 + round(.,1)
        return self._median3_round1(key, y)

    # ---------------------------- API ----------------------------

    def compute(self, image_shape, results_pose, results_hands) -> Dict[str, object]:
        now = now_ms()
        self._frame_id += 1
        p = CONFIG.profile

        # Pose pixels and visibility
        pixels = collect_pose_pixels(image_shape, results_pose)
        vis_list = visibility_list(results_pose)
        avg_vis = average_visibility(vis_list)
        visible_points_count = int(sum(1 for v in vis_list if v > 0.5))
        detected = bool(results_pose and getattr(results_pose, "pose_landmarks", None))
        frame_w = int(image_shape[1] if len(image_shape) > 1 else 0)
        frame_h = int(image_shape[0] if len(image_shape) > 0 else 0)

        # KPS for gates & scale
        kps = kps_from_pose(image_shape, results_pose)

        # View estimation
        mode, view_score = estimate_view(kps, thr=p.visibility.conf_thr)

        # Joints & torso & alignment
        joints = compute_joint_angles(pixels)
        torso = compute_torso(pixels)
        align = compute_foot_and_alignment(pixels)

        # --- Widths / ratios ---
        sh_w, ft_w, grip_w, feet_over, grip_over = compute_widths_and_ratios(pixels, kps)

        # --- Side metrics (raw) ---
        torso_side_raw = compute_torso_forward_side_deg(pixels)
        spine_curve_side_raw = compute_spine_curvature_side(pixels)

        # --- Filters stack על side metrics ---
        torso_side = self._apply_filters("torso_forward_side", "angle", torso_side_raw, avg_vis, sh_w)
        spine_curve_side = self._apply_filters("spine_curvature_side", "angle", spine_curve_side_raw, avg_vis, sh_w)

        # --- מהירויות/תאוצות של side metrics ---
        _, _, _, dt_ms_local = self.filters["torso_forward_side"].update(None, conf=avg_vis)
        _, spine_curve_vel, spine_curve_acc, _ = self.filters["spine_curvature_side"].update(None, conf=avg_vis)

        # --- Jitter updates (side) ---
        self.jitter["torso_forward_side"].update(torso_side if torso_side is not None else torso_side_raw)
        self.jitter["spine_curvature_side"].update(spine_curve_side if spine_curve_side is not None else spine_curve_side_raw)

        # Hands
        grip_L, grip_R = grip_state_from_hands(results_hands)
        wflex_L, wflex_R, wradul_L, wradul_R = wrist_angles(pixels)
        hand_orient_L = hand_orientation(results_hands, "left")
        hand_orient_R = hand_orientation(results_hands, "right")

        # Feet contact / Heel lift (raw)
        cl, cr, ll, lr = feet_contact(pixels, scale_px=sh_w)

        # --- היסטרזיס + ערבוב קונפידנס נקודות רגל ---
        def _avg_conf(names: List[str]) -> float:
            vals = []
            for n in names:
                pnt = kps.get(n)
                try:
                    if isinstance(pnt, (tuple, list)) and len(pnt) >= 3:
                        vals.append(float(pnt[2]))
                    elif pnt is not None and hasattr(pnt, "get"):
                        vals.append(float(pnt.get("conf", 0.0) or 0.0))
                except Exception:
                    pass
            return float(sum(vals) / len(vals)) if vals else float(avg_vis)

        score_fcl = 0.5 * (1.0 if bool(cl) else 0.0) + 0.5 * _avg_conf(["left_heel", "left_foot_index"])
        score_fcr = 0.5 * (1.0 if bool(cr) else 0.0) + 0.5 * _avg_conf(["right_heel", "right_foot_index"])
        score_hll = 0.5 * (1.0 if bool(ll) else 0.0) + 0.5 * _avg_conf(["left_heel", "left_foot_index"])
        score_hlr = 0.5 * (1.0 if bool(lr) else 0.0) + 0.5 * _avg_conf(["right_heel", "right_foot_index"])

        cl_hys = self.foot_contact_left_hys.update(score_fcl)
        cr_hys = self.foot_contact_right_hys.update(score_fcr)
        ll_hys = self.heel_lift_left_hys.update(score_hll)
        lr_hys = self.heel_lift_right_hys.update(score_hlr)

        # Weight shift
        wshift = weight_shift(pixels, sh_w)

        # --- Temporal filters (זוויות מרכזיות של מפרקים – EMA רגיל) ---
        knee_L = self._apply_filters("knee_left", "angle", joints.get("knee_left_deg"), avg_vis, sh_w)
        knee_R = self._apply_filters("knee_right", "angle", joints.get("knee_right_deg"), avg_vis, sh_w)
        hip_L = self._apply_filters("hip_left", "angle", joints.get("hip_left_deg"), avg_vis, sh_w)
        hip_R = self._apply_filters("hip_right", "angle", joints.get("hip_right_deg"), avg_vis, sh_w)
        sh_L = self._apply_filters("shoulder_left", "angle", joints.get("shoulder_left_deg"), avg_vis, sh_w)
        sh_R = self._apply_filters("shoulder_right", "angle", joints.get("shoulder_right_deg"), avg_vis, sh_w)
        torso_flex = self._apply_filters("torso_forward", "angle", torso.get("torso_forward_deg"), avg_vis, sh_w)

        # --- מרפקים: EMA רגיל + median-3 + round ---
        elbow_L = self._apply_filters("elbow_left", "angle", joints.get("elbow_left_deg"), avg_vis, sh_w)
        elbow_R = self._apply_filters("elbow_right", "angle", joints.get("elbow_right_deg"), avg_vis, sh_w)

        # --- Head / Neck metrics ---
        head = compute_head_metrics(pixels=pixels, kps=kps)  # dict: yaw/pitch/roll/confidence/ok
        head_yaw   = guard_head_signed_angle_deg(head.get("yaw"))
        head_pitch = guard_head_signed_angle_deg(head.get("pitch"))
        head_roll  = guard_head_signed_angle_deg(head.get("roll"))
        head_conf  = guard_confidence(head.get("confidence"))
        head_ok_num = 1.0 if bool(head.get("ok", False)) else 0.0  # שומר מספר 0/1

        # --- Build raw payload ---
        pr: Dict[str, object] = {}
        pr.update({
            # --- Joint Angles ---
            "knee_left_deg": knee_L if knee_L is not None else self._round1(joints.get("knee_left_deg")),
            "knee_right_deg": knee_R if knee_R is not None else self._round1(joints.get("knee_right_deg")),
            "hip_left_deg": hip_L if hip_L is not None else self._round1(joints.get("hip_left_deg")),
            "hip_right_deg": hip_R if hip_R is not None else self._round1(joints.get("hip_right_deg")),
            "elbow_left_deg": self._median3_round1("elbow_left_out", elbow_L if elbow_L is not None else self._round1(joints.get("elbow_left_deg"))),
            "elbow_right_deg": self._median3_round1("elbow_right_out", elbow_R if elbow_R is not None else self._round1(joints.get("elbow_right_deg"))),
            "shoulder_left_deg": sh_L if sh_L is not None else self._round1(joints.get("shoulder_left_deg")),
            "shoulder_right_deg": sh_R if sh_R is not None else self._round1(joints.get("shoulder_right_deg")),
            "ankle_dorsi_left_deg": self._round1(joints.get("ankle_dorsi_left_deg")),
            "ankle_dorsi_right_deg": self._round1(joints.get("ankle_dorsi_right_deg")),

            # --- Torso & Spine ---
            "torso_forward_deg": torso_flex if torso_flex is not None else self._round1(torso.get("torso_forward_deg")),
            "torso_vs_vertical_deg": self._round1(torso.get("torso_vs_vertical_deg")),
            "torso_vs_horizontal_deg": self._round1(torso.get("torso_vs_horizontal_deg")),
            "spine_flexion_deg": self._round1(torso.get("spine_flexion_deg")),

            "torso_forward_side_deg": gate_metric("torso_forward_side_deg", kps, mode, self._round1(torso_side)),
            "spine_curvature_side_deg": gate_metric("spine_curvature_side_deg", kps, mode, self._round1(spine_curve_side)),
            "spine_curvature_side_vel_deg_s": gate_metric("spine_curvature_side_vel_deg_s", kps, mode, self._round1(spine_curve_vel)),
            "spine_curvature_side_acc_deg_s2": gate_metric("spine_curvature_side_acc_deg_s2", kps, mode, self._round1(spine_curve_acc)),

            # --- Feet & Alignment ---
            "toe_angle_left_deg": gate_metric("toe_angle_left_deg", kps, mode, self._round1(align.get("toe_angle_left_deg"))),
            "toe_angle_right_deg": gate_metric("toe_angle_right_deg", kps, mode, self._round1(align.get("toe_angle_right_deg"))),
            "knee_foot_alignment_left_deg": gate_metric("knee_foot_alignment_left_deg", kps, mode, self._round1(align.get("knee_foot_alignment_left_deg"))),
            "knee_foot_alignment_right_deg": gate_metric("knee_foot_alignment_right_deg", kps, mode, self._round1(align.get("knee_foot_alignment_right_deg"))),
            "foot_contact_left": bool(cl_hys) if cl_hys is not None else None,
            "foot_contact_right": bool(cr_hys) if cr_hys is not None else None,
            "heel_lift_left": bool(ll_hys) if ll_hys is not None else None,
            "heel_lift_right": bool(lr_hys) if lr_hys is not None else None,

            # --- Widths & Ratios ---
            "shoulders_width_px": sh_w,
            "feet_width_px": ft_w,
            "grip_width_px": grip_w,
            "feet_w_over_shoulders_w": feet_over,
            "grip_w_over_shoulders_w": grip_over,

            # --- Hands ---
            "wrist_flex_ext_left_deg": self._round1(wflex_L),
            "wrist_flex_ext_right_deg": self._round1(wflex_R),
            "wrist_radial_ulnar_left_deg": self._round1(wradul_L),
            "wrist_radial_ulnar_right_deg": self._round1(wradul_R),
            "grip_state_left": grip_L,
            "grip_state_right": grip_R,
            "hand_orientation_left": hand_orient_L,
            "hand_orientation_right": hand_orient_R,
            "hand_orientation_left_he": he(hand_orient_L),
            "hand_orientation_right_he": he(hand_orient_R),

            # --- Head (flat) ---
            "head_yaw_deg": head_yaw,
            "head_pitch_deg": head_pitch,
            "head_roll_deg": head_roll,
            "head_confidence": head_conf,
            "head_ok": head_ok_num,  # 1.0/0.0

            # --- Symmetry & Weight ---
            "knee_delta_deg": self._round1(self._delta_deg_simple(joints.get("knee_left_deg"), joints.get("knee_right_deg"))),
            "hip_delta_deg": self._round1(self._delta_deg_simple(joints.get("hip_left_deg"), joints.get("hip_right_deg"))),
            "shoulders_delta_px": gate_metric(
                "shoulders_delta_px", kps, mode,
                (float(P(pixels, "left_shoulder")[1] - P(pixels, "right_shoulder")[1])
                 if P(pixels, "left_shoulder") and P(pixels, "right_shoulder") else None)
            ),
            "hips_delta_px": gate_metric(
                "hips_delta_px", kps, mode,
                (float(P(pixels, "left_hip")[1] - P(pixels, "right_hip")[1])
                 if P(pixels, "left_hip") and P(pixels, "right_hip") else None)
            ),
            "weight_shift": wshift,

            # --- Temporal values (subset; useful for debugging) ---
            "torso_forward_vel_deg_s": None,
            "torso_forward_acc_deg_s2": None,
            "dt_ms": dt_ms_local,

            # --- Jitter values (subset) ---
            "torso_forward_side_jitter_std": self.jitter["torso_forward_side"].std(),
            "spine_curvature_side_jitter_std": self.jitter["spine_curvature_side"].std(),

            # --- Meta & Quality ---
            "view_mode": mode,
            "view_score": view_score,
            "average_visibility": avg_vis,
            "visible_points_count": visible_points_count,
            "confidence": float(avg_vis),
            "quality_score": float(min(100.0, max(0.0, avg_vis * 100.0))),
            "low_confidence": bool(avg_vis < 0.5),
            "frame.w": frame_w,
            "frame.h": frame_h,
            "meta.detected": bool(detected),
            "meta.updated_at": int(now),
            "meta.age_ms": 0,

            # UI (רשות)
            "ui.conf_category": ui_color_for_conf(float(avg_vis), p.ui),

            # Optional overlay
            "pose2d": optional_pose2d(pixels),
        })

        # ==================== COMPAT WRAPPER FOR TESTER ====================
        # הטסטר של האוף־ליין מצפה ל:
        # 1) מפתח "measurements" עם מדדים מרכזיים + ".quality"
        # 2) מפתחות "meta.pose_visibility", "meta.hands_detected", "meta.image_w/h"
        #
        # כאן אנחנו מוסיפים שכבה תואמת — בנוסף ל־payload המלא שכבר בנוי ב-pr

        # 2.1 זיהוי מספר ידיים (גם אם אין Hands אמיתי – יתן 0)
        try:
            _hands_list = getattr(results_hands, "multi_hand_landmarks", []) or []
            _hands_detected = int(len(_hands_list))
        except Exception:
            _hands_detected = 0

        # 2.2 חשיפת pose_visibility ברמת meta.* (הטסטר מחפש flatten)
        pr["meta.pose_visibility"] = float(avg_vis) if avg_vis is not None else None
        pr["meta.hands_detected"] = int(_hands_detected)
        pr["meta.image_w"] = int(frame_w)
        pr["meta.image_h"] = int(frame_h)

        # 1) measurements – הטסטר סופר כמה מפתחות לא-None יש כאן
        #    בחרתי 4 מדדים ליבה + quality פשוט על סמך visibility (0..1)
        def _q(val):
            # אם יש ערך—quality לפי avg_vis; אם אין—None כדי שהטסטר לא יחשב את זה
            return float(max(0.0, min(1.0, avg_vis))) if (val is not None and isinstance(avg_vis, (int, float))) else None

        _m_knee_right = pr.get("knee_right_deg")
        _m_elbow_left = pr.get("elbow_left_deg")
        _m_torso_flex = pr.get("torso_forward_deg")
        _m_head_pitch = pr.get("head_pitch_deg")

        pr["measurements"] = {
            "knee_right_deg": _m_knee_right,
            "knee_right_deg.quality": _q(_m_knee_right),

            "elbow_left_deg": _m_elbow_left,
            "elbow_left_deg.quality": _q(_m_elbow_left),

            "torso_forward_deg": _m_torso_flex,
            "torso_forward_deg.quality": _q(_m_torso_flex),

            "head_pitch_deg": _m_head_pitch,
            "head_pitch_deg.quality": _q(_m_head_pitch),
        }
        # ================== END COMPAT WRAPPER FOR TESTER ===================

        # ---------------- Guards: סילוק NaN/Inf וערכים לא הגיוניים ----------------
        for k in list(pr.keys()):
            v = pr[k]
            if isinstance(v, (int, float)):
                pr[k] = guard_number(v)

        # זוויות מפרקים (0..200)
        for k in ("knee_left_deg", "knee_right_deg", "hip_left_deg", "hip_right_deg",
                  "ankle_dorsi_left_deg", "ankle_dorsi_right_deg",
                  "elbow_left_deg", "elbow_right_deg",
                  "shoulder_left_deg", "shoulder_right_deg"):
            pr[k] = guard_joint_angle_deg(pr.get(k))

        # זוויות חתומות/מעלות (כולל side + head)
        for k in ("torso_forward_deg", "torso_vs_vertical_deg", "torso_vs_horizontal_deg", "spine_flexion_deg",
                  "torso_forward_side_deg", "spine_curvature_side_deg",
                  "toe_angle_left_deg", "toe_angle_right_deg",
                  "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
                  "knee_delta_deg", "hip_delta_deg",
                  "wrist_flex_ext_left_deg", "wrist_flex_ext_right_deg",
                  "wrist_radial_ulnar_left_deg", "wrist_radial_ulnar_right_deg",
                  "head_yaw_deg", "head_pitch_deg", "head_roll_deg"):
            pr[k] = guard_signed_angle_deg(pr.get(k))

        # יחסים (רוחבים) – חיובי וסביר
        for k in ("feet_w_over_shoulders_w", "grip_w_over_shoulders_w"):
            pr[k] = guard_ratio(pr.get(k))

        # Confidence לראש (0..1)
        pr["head_confidence"] = guard_confidence(pr.get("head_confidence"))

        # ---------------- Gating: לפי נראות + View ----------------
        def keep_meta(key: str) -> bool:
            return (key.startswith("meta.") or key.startswith("frame.") or key in {
                "average_visibility", "visible_points_count", "confidence", "quality_score",
                "low_confidence", "view_mode", "view_score", "dt_ms", "pose2d",
                "shoulders_width_px", "feet_width_px", "grip_width_px",
                "feet_w_over_shoulders_w", "grip_w_over_shoulders_w",
                # Bypass double gating for targeted metrics (already gated via gate_metric)
                "torso_forward_side_deg",
                "spine_curvature_side_deg", "spine_curvature_side_vel_deg_s", "spine_curvature_side_acc_deg_s2",
                "toe_angle_left_deg", "toe_angle_right_deg",
                "knee_foot_alignment_left_deg", "knee_foot_alignment_right_deg",
                "shoulders_delta_px", "hips_delta_px",
                "torso_forward_side_jitter_std", "spine_curvature_side_jitter_std",
                "ui.conf_category",
                # head_* ללא gating
                "head_yaw_deg", "head_pitch_deg", "head_roll_deg", "head_confidence", "head_ok",
            })

        def reqs_for(key: str) -> List[str]:
            kl = key.lower()
            if "knee_left" in kl: return ["left_hip", "left_knee", "left_ankle"]
            if "knee_right" in kl: return ["right_hip", "right_knee", "right_ankle"]
            if "hip_left" in kl: return ["left_shoulder", "left_hip", "left_knee"]
            if "hip_right" in kl: return ["right_shoulder", "right_hip", "right_knee"]
            if "ankle_dorsi_left" in kl: return ["left_knee", "left_ankle", "left_foot_index"]
            if "ankle_dorsi_right" in kl: return ["right_knee", "right_ankle", "right_foot_index"]
            if "shoulder_left_deg" in kl: return ["left_elbow", "left_shoulder", "left_hip"]
            if "shoulder_right_deg" in kl: return ["right_elbow", "right_shoulder", "right_hip"]
            if "elbow_left" in kl: return ["left_shoulder", "left_elbow", "left_wrist"]
            if "elbow_right" in kl: return ["right_shoulder", "right_elbow", "right_wrist"]
            if "toe_angle_left" in kl: return ["left_heel", "left_foot_index"]
            if "toe_angle_right" in kl: return ["right_heel", "right_foot_index"]
            if "knee_foot_alignment_left" in kl: return ["left_hip", "left_knee", "left_ankle", "left_heel", "left_foot_index"]
            if "knee_foot_alignment_right" in kl: return ["right_hip", "right_knee", "right_ankle", "right_heel", "right_foot_index"]
            if "wrist_flex_ext_left" in kl or "wrist_radial_ulnar_left" in kl: return ["left_wrist", "left_index", "left_pinky"]
            if "wrist_flex_ext_right" in kl or "wrist_radial_ulnar_right" in kl: return ["right_wrist", "right_index", "right_pinky"]
            if "shoulders_delta_px" in kl: return ["left_shoulder", "right_shoulder"]
            if "hips_delta_px" in kl: return ["left_hip", "right_hip"]
            if "weight_shift" in kl: return ["left_heel", "right_heel", "left_hip", "right_hip"]
            if "spine_curvature_side" in kl or "torso_forward_side" in kl:
                return ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]
            # head_*: ללא דרישות gating כרגע
            return []

        def views_for(key: str) -> Tuple[str, ...]:
            kl = key.lower()
            if "spine_curvature_side" in kl or "torso_forward_side" in kl:
                return ("side",)
            if any(s in kl for s in ("toe_angle", "knee_foot_alignment", "shoulders_delta", "hips_delta")):
                return ("front", "back")
            return ("any",)

        gated: Dict[str, object] = {}
        for k, v in pr.items():
            if keep_meta(k):
                gated[k] = v
                continue
            reqs = reqs_for(k)
            allow_views = views_for(k)

            def _ret(_kps):
                return v

            outv = compute_if_visible(kps, reqs, _ret, thr=p.visibility.conf_thr, views=allow_views) if reqs else v
            if outv is not None:
                gated[k] = outv

        # ---------------- LKG: שמירת אחרון תקין עד max_age_ms ----------------
        out = self.lkg.apply(detected=detected, payload=gated, conf=avg_vis)

        # ---------------- Nested duplicates (frame/meta) + schema fill ----------------
        try:
            dt_ms_val = out.get("dt_ms")
            fps_est = (1000.0 / float(dt_ms_val)) if isinstance(dt_ms_val, (int, float)) and float(dt_ms_val) > 0.0 else 0.0
        except Exception:
            fps_est = 0.0

        nested_meta = {
            "payload_version": PAYLOAD_VERSION,
            "frame_id": int(self._frame_id),
            "fps_est": float(fps_est),
            "detected": bool(out.get("meta.detected", False)),
            "valid": bool(out.get("meta.valid", False)),
            "updated_at_ms": int(out.get("meta.updated_at", 0) or 0),
            "age_ms": int(out.get("meta.age_ms", 0) or 0),
        }
        nested_frame = {
            "w": int(out.get("frame.w", 0) or 0),
            "h": int(out.get("frame.h", 0) or 0),
        }

        out["meta"] = nested_meta
        out["frame"] = nested_frame

        # ---- ELBOW ANGLES FIX: final fallback מהפיקסלים ----
        def _elbow_deg_from_pixels(side: str):
            """Angle 0..180° ב־מרפק: shoulder—elbow—wrist."""
            try:
                import math
                shoulder = P(pixels, f"{side}_shoulder")
                elbow    = P(pixels, f"{side}_elbow")
                wrist    = P(pixels, f"{side}_wrist")
                if not (shoulder and elbow and wrist):
                    return None
                v1 = (float(shoulder[0]) - float(elbow[0]), float(shoulder[1]) - float(elbow[1]))
                v2 = (float(wrist[0])   - float(elbow[0]),  float(wrist[1])   - float(elbow[1]))
                m1 = (v1[0]*v1[0] + v1[1]*v1[1]) ** 0.5
                m2 = (v2[0]*v2[0] + v2[1]*v2[1]) ** 0.5
                if m1 < 1e-6 or m2 < 1e-6:
                    return None
                c = (v1[0]*v2[0] + v1[1]*v2[1]) / (m1*m2)
                if c < -1.0: c = -1.0
                if c >  1.0: c =  1.0
                ang = math.degrees(math.acos(c))
                return round(float(ang), 1)
            except Exception:
                return None

        if out.get("elbow_left_deg") is None:
            _v = _elbow_deg_from_pixels("left")
            if _v is not None:
                out["elbow_left_deg"] = _v
        if out.get("elbow_right_deg") is None:
            _v = _elbow_deg_from_pixels("right")
            if _v is not None:
                out["elbow_right_deg"] = _v

        payload = fill_schema(out)

        # =============== DUAL-EMIT MODE (v1.2.0) ===============
        # Support both legacy and new payload formats
        if USE_NEW_PAYLOAD and _PAYLOAD_AVAILABLE:
            try:
                # Convert legacy dict to new Payload format
                payload_obj = from_kinematics_output(payload)
                return payload_obj.to_dict()
            except Exception as e:
                # Fallback to legacy if conversion fails
                print(f"[KINEMATICS] Warning: Failed to convert to new payload format: {e}")
                return payload
        else:
            # Legacy mode (default)
            return payload


# >>> ADDED: סינגלטון ייצוא נוח ל-import חיצוני
KINEMATICS = KinematicsComputer()
