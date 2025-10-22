# -*- coding: utf-8 -*-
"""
test_kinematics_offline_full.py — סוויטת בדיקות אמינות לקינמטיקה (אופליין)
----------------------------------------------------------------------------
מטרות:
1) אימות מבני: שכל השדות הקריטיים קיימים (rep.*, metrics.*, angles.* וכו').
2) אימות מספרי: ללא NaN/Inf, תחומי ערכים הגיוניים (זוויות, מהירויות, FPS).
3) עקביות: מונוטוניות של זמן/מיספור פריימים, שינויים סבירים בין פריימים.
4) סימטריה: פערים סבירים בין צד שמאל לימין (ברך/ירך/מרפק/כתף).
5) "אורך עצמות": אם קיימות נקודות שלד (x,y[,z]), שהאורכים לא "קופצים" בין פריימים.
6) מיועד לעבוד בלי תלות במנוע — נתונים מובנים בתוך הקוד; אופציונלית אפשר JSON אמיתי.

שימוש:
- פשוט להריץ:  python test_kinematics_offline_full.py
- אופציונלי: להצביע על פיילוד אמיתי (JSON) דרך משתנה סביבה:
    set KINEMATICS_JSON=reports/payload_sample.json
    python test_kinematics_offline_full.py
"""

from __future__ import annotations
import os, json, math, unittest
from typing import Any, Dict, List, Tuple, Optional

# ────────────────────────────────────────────────────────────────────────────
# נתוני דמה מובנים (אפשר לערוך כאן כדי לבדוק תרחישים שונים)
# מבנה כללי (גמיש): רשימת פריימים; כל פריים מכיל:
# - timestamp (float ms או s), frame_id (int), fps (optional)
# - angles: מילון זוויות (מעלות)
# - angles_left / angles_right לסימטריה
# - joints: נקודות שלד {"LEFT_KNEE": [x,y], "LEFT_HIP": [x,y], ...} [0..1] נורמליזציה למסך
# - metrics/rep: לא חובה, אבל נבדוק אם קיימים
# שים לב: זה דמה אמין עם שינוי עדין בין פריימים.
# ────────────────────────────────────────────────────────────────────────────

SAMPLE_FRAMES: List[Dict[str, Any]] = [
    {
        "timestamp": 0.000, "frame_id": 1, "fps": 30.0,
        "angles": {"knee": 120.0, "hip": 140.0, "shoulder": 35.0},
        "angles_left": {"knee": 121.0, "hip": 139.0, "elbow": 50.0, "shoulder": 36.0},
        "angles_right": {"knee": 118.5, "hip": 141.5, "elbow": 52.0, "shoulder": 34.0},
        "joints": {
            "LEFT_HIP": [0.40, 0.60], "LEFT_KNEE": [0.42, 0.80], "LEFT_ANKLE": [0.44, 0.95],
            "RIGHT_HIP": [0.60, 0.60], "RIGHT_KNEE": [0.58, 0.80], "RIGHT_ANKLE": [0.56, 0.95],
            "LEFT_SHOULDER": [0.42, 0.40], "RIGHT_SHOULDER": [0.58, 0.40]
        },
        "rep": {"state": "active", "progress": 0.30},
        "metrics": {"pose_conf": 0.95}
    },
    {
        "timestamp": 0.033, "frame_id": 2, "fps": 30.0,
        "angles": {"knee": 121.0, "hip": 139.0, "shoulder": 35.2},
        "angles_left": {"knee": 122.0, "hip": 138.0, "elbow": 50.5, "shoulder": 36.2},
        "angles_right": {"knee": 119.0, "hip": 141.0, "elbow": 52.2, "shoulder": 34.2},
        "joints": {
            "LEFT_HIP": [0.401, 0.600], "LEFT_KNEE": [0.421, 0.801], "LEFT_ANKLE": [0.441, 0.952],
            "RIGHT_HIP": [0.599, 0.600], "RIGHT_KNEE": [0.579, 0.801], "RIGHT_ANKLE": [0.559, 0.952],
            "LEFT_SHOULDER": [0.421, 0.401], "RIGHT_SHOULDER": [0.579, 0.401]
        },
        "rep": {"state": "active", "progress": 0.35},
        "metrics": {"pose_conf": 0.94}
    },
    {
        "timestamp": 0.066, "frame_id": 3, "fps": 29.8,
        "angles": {"knee": 122.0, "hip": 138.0, "shoulder": 35.4},
        "angles_left": {"knee": 123.0, "hip": 137.5, "elbow": 51.0, "shoulder": 36.5},
        "angles_right": {"knee": 120.0, "hip": 140.5, "elbow": 52.4, "shoulder": 34.4},
        "joints": {
            "LEFT_HIP": [0.402, 0.600], "LEFT_KNEE": [0.422, 0.802], "LEFT_ANKLE": [0.442, 0.954],
            "RIGHT_HIP": [0.598, 0.600], "RIGHT_KNEE": [0.578, 0.802], "RIGHT_ANKLE": [0.558, 0.954],
            "LEFT_SHOULDER": [0.420, 0.402], "RIGHT_SHOULDER": [0.580, 0.402]
        },
        "rep": {"state": "active", "progress": 0.40},
        "metrics": {"pose_conf": 0.94}
    },
]

# אם יש JSON אמיתי — נטען אותו במקום SAMPLE_FRAMES (לא חובה)
ENV_JSON = os.environ.get("KINEMATICS_JSON")
def _load_frames() -> List[Dict[str, Any]]:
    if ENV_JSON and os.path.isfile(ENV_JSON):
        with open(ENV_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        # מקבלים או רשימת פריימים ישירות, או אובייקט עם "frames"
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "frames" in data and isinstance(data["frames"], list):
            return data["frames"]
        raise ValueError("KINEMATICS_JSON נטען אך הפורמט אינו נתמך (צפה לרשימה של פריימים או {frames:[...]})")
    return SAMPLE_FRAMES


# ────────────────────────────────────────────────────────────────────────────
# Utilities
# ────────────────────────────────────────────────────────────────────────────

def is_finite_number(x: Any) -> bool:
    try:
        return isinstance(x, (int, float)) and math.isfinite(float(x))
    except Exception:
        return False

def dist2d(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def approx_equal(a: float, b: float, atol: float) -> bool:
    return abs(a - b) <= atol


# ────────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────────

class TestKinematicsOfflineFull(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.frames = _load_frames()
        assert isinstance(cls.frames, list) and cls.frames, "אין פריימים לבדיקה"

    # 1) בדיקות מבנה ושדות
    def test_structure_required_fields(self):
        required_top = ["timestamp", "frame_id", "angles"]
        for i, fr in enumerate(self.frames):
            for k in required_top:
                self.assertIn(k, fr, f"פריים {i}: חסר שדה חובה '{k}'")
            self.assertIsInstance(fr["angles"], dict, f"פריים {i}: angles חייב להיות מילון")

    # 2) בדיקות מספריות: אין NaN/Inf וזוויות בטווח סביר (0..210)
    def test_numeric_and_ranges(self):
        for i, fr in enumerate(self.frames):
            # timestamp
            self.assertTrue(is_finite_number(fr["timestamp"]), f"פריים {i}: timestamp לא תקין")
            # fps אם קיים
            if "fps" in fr:
                self.assertTrue(5.0 <= float(fr["fps"]) <= 120.0, f"פריים {i}: fps לא סביר: {fr['fps']}")
            # angles
            for name, val in fr["angles"].items():
                self.assertTrue(is_finite_number(val), f"פריים {i}: זווית {name} אינה מספרית")
                self.assertTrue(0.0 <= float(val) <= 210.0, f"פריים {i}: זווית {name} מחוץ לטווח [0..210]: {val}")

    # 3) מונוטוניות זמן ומיספור פריימים + שינוי סביר בין פריימים עוקבים
    def test_monotonicity_and_delta_limits(self):
        max_angle_delta_per_frame = 10.0  # מעלות לפריים (נמוך כדי לתפוס "קפיצות")
        prev_ts = None
        prev_id = None
        prev_angles = None

        for i, fr in enumerate(self.frames):
            ts = float(fr["timestamp"])
            fid = int(fr["frame_id"])

            if prev_ts is not None:
                self.assertGreater(ts, prev_ts, f"פריים {i}: timestamp לא עולה (prev={prev_ts}, now={ts})")
            if prev_id is not None:
                self.assertGreater(fid, prev_id, f"פריים {i}: frame_id לא עולה (prev={prev_id}, now={fid})")

            # דלתא זוויות סבירה
            if prev_angles is not None:
                for name, val in fr["angles"].items():
                    if name in prev_angles and is_finite_number(val) and is_finite_number(prev_angles[name]):
                        self.assertLessEqual(abs(val - prev_angles[name]), max_angle_delta_per_frame,
                                             f"פריים {i}: קפיצה חדה בזווית {name} ({prev_angles[name]} → {val})")

            prev_ts = ts
            prev_id = fid
            prev_angles = fr["angles"]

    # 4) סימטריה: פער שמאל/ימין לא יחרוג מסף סביר (למשל 35°)
    def test_left_right_symmetry(self):
        max_side_gap = 35.0
        for i, fr in enumerate(self.frames):
            left = fr.get("angles_left") or {}
            right = fr.get("angles_right") or {}
            common = set(left.keys()).intersection(right.keys())
            for name in common:
                L, R = left[name], right[name]
                if is_finite_number(L) and is_finite_number(R):
                    self.assertLessEqual(abs(L - R), max_side_gap,
                                         f"פריים {i}: פער גדול מידי בין צדדים בזווית {name}: {L} vs {R}")

    # 5) אורך מקטעים ("עצמות") יציב בין פריימים (אם joints זמינים)
    def test_skeleton_segment_stability(self):
        # נבדוק מקטעי רגל ושכמה בסיסיים:
        segments = [
            ("LEFT_HIP", "LEFT_KNEE"),
            ("LEFT_KNEE", "LEFT_ANKLE"),
            ("RIGHT_HIP", "RIGHT_KNEE"),
            ("RIGHT_KNEE", "RIGHT_ANKLE"),
            ("LEFT_SHOULDER", "RIGHT_SHOULDER"),
        ]
        # אם אין joints — נדלג
        if not all("joints" in fr for fr in self.frames):
            self.skipTest("אין joints בפריימים — דילוג על בדיקת עצמות.")
            return

        # מחשבים אורכי עצמות בפריים ראשון כייחוס
        baseline: Dict[str, float] = {}
        first = self.frames[0]["joints"]
        for a, b in segments:
            if a in first and b in first:
                baseline[f"{a}-{b}"] = dist2d(tuple(first[a]), tuple(first[b]))

        # סבילות (יחסית): 10% שינוי באורך הוא הרבה — נציב 0.12 כדי לתפוס קפיצות
        rel_tol = 0.12

        for i, fr in enumerate(self.frames[1:], start=1):
            joints = fr.get("joints") or {}
            for a, b in segments:
                key = f"{a}-{b}"
                if key in baseline and a in joints and b in joints:
                    curr = dist2d(tuple(joints[a]), tuple(joints[b]))
                    base = baseline[key]
                    # אם הבייסליין קטן מאד, דלג (שומר על יציבות מתמטית)
                    if base <= 1e-6:
                        continue
                    ratio = abs(curr - base) / base
                    self.assertLessEqual(ratio, rel_tol,
                                         f"פריים {i}: קפיצה באורך '{key}' base={base:.4f} → curr={curr:.4f} (ratio={ratio:.2%})")

    # 6) שדות rep/metrics אם קיימים — בדיקות מינימום
    def test_rep_and_metrics_minimal(self):
        for i, fr in enumerate(self.frames):
            rep = fr.get("rep")
            if rep:
                self.assertIn("state", rep, f"פריים {i}: rep בלי state")
                # progress אם קיים — 0..1
                if "progress" in rep:
                    self.assertTrue(0.0 <= float(rep["progress"]) <= 1.0,
                                    f"פריים {i}: rep.progress מחוץ לטווח 0..1")
            metrics = fr.get("metrics")
            if metrics:
                # ערכי confidence אם קיימים — 0..1
                for k in ["pose_conf", "objdet_conf", "hands_conf"]:
                    if k in metrics:
                        self.assertTrue(0.0 <= float(metrics[k]) <= 1.0,
                                        f"פריים {i}: metrics.{k} מחוץ לטווח 0..1")

    # 7) sanity על “סקוואט” כללי: ברך בין ~90..180, ירך בין ~60..180 (לא חובה — רק אם קיימות)
    def test_generic_squat_sanity(self):
        for i, fr in enumerate(self.frames):
            ang = fr.get("angles", {})
            if "knee" in ang and is_finite_number(ang["knee"]):
                self.assertTrue(90.0 <= ang["knee"] <= 180.0,
                                f"פריים {i}: knee מחוץ לטווח סקוואט סביר: {ang['knee']}")
            if "hip" in ang and is_finite_number(ang["hip"]):
                self.assertTrue(60.0 <= ang["hip"] <= 180.0,
                                f"פריים {i}: hip מחוץ לטווח סקוואט סביר: {ang['hip']}")

    # 8) אם קיים fps — נגזור גם Δt≈1/fps ונבדוק התאמה גסה
    def test_fps_vs_timestep(self):
        # מרחק זמן בין פריימים ~ 1/fps (נעשה סבילות רחבה)
        if len(self.frames) < 2:
            self.skipTest("פחות משני פריימים — דילוג על בדיקת Δt.")
            return

        for i in range(1, len(self.frames)):
            f_prev, f_curr = self.frames[i-1], self.frames[i]
            if "fps" in f_prev and is_finite_number(f_prev["fps"]):
                fps = float(f_prev["fps"])
                if fps <= 0:
                    continue
                dt = float(f_curr["timestamp"]) - float(f_prev["timestamp"])
                expected_dt = 1.0 / fps
                # סבילות גסה (±60%) — אנחנו לא תלויים בשעון מושלם
                self.assertTrue(0.4 * expected_dt <= dt <= 1.6 * expected_dt,
                                f"פריים {i}: Δt={dt:.4f} לא עקבי מול fps={fps} (expected≈{expected_dt:.4f})")


if __name__ == "__main__":
    unittest.main(verbosity=2)
