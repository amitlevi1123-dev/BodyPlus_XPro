# core/kinematics/pose_points.py
# -------------------------------------------------------
# 📌 Pose points helpers:
#   - PoseIdx: MediaPipe Pose indices (0.10.x)
#   - collect_pose_pixels: build dict name -> (x, y) in pixels (or None)
#   - visibility_list: list of landmark visibilities
#   - kps_from_pose: build dict name -> (x, y, conf) for visibility gates
#   - ALIAS + P(): friendly access with alternative keys
#   - optional_pose2d: 2D pose points for overlay only
# -------------------------------------------------------

from __future__ import annotations
from typing import Dict, Tuple, Optional, List

from ..geometry import center_point  # for external callers if needed


class PoseIdx:
    NOSE = 0
    LEFT_EYE_INNER = 1
    LEFT_EYE = 2
    LEFT_EYE_OUTER = 3
    RIGHT_EYE_INNER = 4
    RIGHT_EYE = 5
    RIGHT_EYE_OUTER = 6
    LEFT_EAR = 7
    RIGHT_EAR = 8
    LEFT_MOUTH = 9
    RIGHT_MOUTH = 10
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_ELBOW = 13
    RIGHT_ELBOW = 14
    LEFT_WRIST = 15
    RIGHT_WRIST = 16
    LEFT_PINKY = 17
    RIGHT_PINKY = 18
    LEFT_INDEX = 19
    RIGHT_INDEX = 20
    LEFT_THUMB = 21
    RIGHT_THUMB = 22
    LEFT_HIP = 23
    RIGHT_HIP = 24
    LEFT_KNEE = 25
    RIGHT_KNEE = 26
    LEFT_ANKLE = 27
    RIGHT_ANKLE = 28
    LEFT_HEEL = 29
    RIGHT_HEEL = 30
    LEFT_FOOT_INDEX = 31
    RIGHT_FOOT_INDEX = 32


def _lm_to_px(image_shape, lm, idx: int) -> Optional[Tuple[float, float]]:
    """Convert normalized landmark to pixel coords (x,y)."""
    if lm is None or image_shape is None or not hasattr(image_shape, "__len__"):
        return None
    try:
        h = int(image_shape[0])
        w = int(image_shape[1]) if len(image_shape) > 1 else 0
        if h <= 0 or w <= 0:
            return None
        p = lm[idx]
        return float(p.x * w), float(p.y * h)
    except Exception:
        return None


def collect_pose_pixels(image_shape, results_pose) -> Dict[str, Optional[Tuple[float, float]]]:
    """Return dict of pose name (lowercase) -> (x,y) in pixels or None."""
    pts: Dict[str, Optional[Tuple[float, float]]] = {}
    names = [n for n in dir(PoseIdx) if n.isupper()]
    # initialize all keys to keep stable shape
    for name in names:
        pts[name.lower()] = None

    if results_pose and getattr(results_pose, "pose_landmarks", None):
        try:
            lm = results_pose.pose_landmarks.landmark
            for name in names:
                idx = getattr(PoseIdx, name)
                pts[name.lower()] = _lm_to_px(image_shape, lm, idx)
        except Exception:
            pass
    return pts


def visibility_list(results_pose) -> List[float]:
    """Return list of landmark visibilities from MediaPipe Pose."""
    vis: List[float] = []
    if results_pose and getattr(results_pose, "pose_landmarks", None):
        try:
            lm = results_pose.pose_landmarks.landmark
            for i in range(len(lm)):
                try:
                    vis.append(float(lm[i].visibility))
                except Exception:
                    vis.append(0.0)
        except Exception:
            return vis
    return vis


def optional_pose2d(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Dict[str, Tuple[float, float]]:
    """Return only existing points, for overlay (pose2d)."""
    out: Dict[str, Tuple[float, float]] = {}
    for k, v in pixels.items():
        if v is not None:
            try:
                out[k] = (float(v[0]), float(v[1]))
            except Exception:
                # skip bad numeric
                continue
    return out


# Aliases and safe accessor
ALIAS = {
    "hip_left": "left_hip", "hip_right": "right_hip",
    "knee_left": "left_knee", "knee_right": "right_knee",
    "ankle_left": "left_ankle", "ankle_right": "right_ankle",
    "shoulder_left": "left_shoulder", "shoulder_right": "right_shoulder",
    "elbow_left": "left_elbow", "elbow_right": "right_elbow",
    "wrist_left": "left_wrist", "wrist_right": "right_wrist",
    "heel_left": "left_heel", "heel_right": "right_heel",
    "toe_left": "left_foot_index", "toe_right": "right_foot_index",
    "foot_index_left": "left_foot_index", "foot_index_right": "right_foot_index",
    "index_left": "left_index", "index_right": "right_index",
    "pinky_left": "left_pinky", "pinky_right": "right_pinky",
    "thumb_left": "left_thumb", "thumb_right": "right_thumb",
}


def P(pixels: Dict[str, Optional[Tuple[float, float]]], key: str) -> Optional[Tuple[float, float]]:
    """Friendly accessor: try key then alias; return None if missing."""
    if not isinstance(key, str):
        return None
    if key in pixels:
        return pixels[key]
    alt = ALIAS.get(key)
    return pixels.get(alt) if alt else None


def kps_from_pose(image_shape, results_pose) -> Dict[str, Tuple[float, float, float]]:
    """Build dict name -> (x,y,conf) from MediaPipe Pose results."""
    out: Dict[str, Tuple[float, float, float]] = {}
    if not (results_pose and getattr(results_pose, "pose_landmarks", None)):
        return out

    names = [n for n in dir(PoseIdx) if n.isupper()]
    try:
        h = int(image_shape[0])
        w = int(image_shape[1]) if len(image_shape) > 1 else 0
        if h <= 0 or w <= 0:
            return out

        lm = results_pose.pose_landmarks.landmark
        for name in names:
            idx = getattr(PoseIdx, name)
            try:
                p = lm[idx]
                x = float(p.x * w)
                y = float(p.y * h)
                c = float(getattr(p, "visibility", 0.0))
                out[name.lower()] = (x, y, c)
            except Exception:
                continue
    except Exception:
        return out
    return out
