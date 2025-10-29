# -*- coding: utf-8 -*-
# =============================================================================
# MediaPipeRunner — ללא OpenCV (Pose + Hands) + פרסום JSON ל-UI
# -----------------------------------------------------------------------------
# מה הוא עושה?
# • מקבל פריים RGB (np.ndarray) ומריץ MediaPipe Pose+Hands.
# • שולח JSON של נקודות ל-admin_web.state.set_last_pose(...).
# • לא מצייר, לא מקודד, לא נוגע ב-MJPEG. הווידאו זורם בנפרד.
#
# שימוש:
#   runner = MediaPipeRunner(enable_pose=True, enable_hands=True, publish_hz=12).start()
#   runner.process(frame_rgb)  # נקרא ע"י main/app
# =============================================================================

from __future__ import annotations
from typing import Optional, Tuple, Dict, Any
import sys, traceback, time

try:
    from core.logs import logger  # type: ignore
    def LOG(level: str, msg: str) -> None: getattr(logger, level, logger.info)(msg)
except Exception:
    def LOG(level: str, msg: str) -> None: print(f"[{level.upper()}] {msg}")

class MediaPipeRunner:
    def __init__(
        self,
        *,
        enable_pose: bool = True,
        enable_hands: bool = True,
        hands_every_n: int = 1,
        pose_model_complexity: int = 1,
        pose_min_det: float = 0.5,
        pose_min_track: float = 0.5,
        hands_max_num: int = 2,
        hands_min_det: float = 0.5,
        hands_min_track: float = 0.5,
        publish_hz: float = 12.0,  # הגבלת קצב פרסום JSON ל-UI
        verbose: bool = True,
    ) -> None:
        self.enable_pose = bool(enable_pose)
        self.enable_hands = bool(enable_hands)
        self.hands_every_n = max(1, int(hands_every_n))
        self.pose_model_complexity = int(pose_model_complexity)
        self.pose_min_det = float(pose_min_det)
        self.pose_min_track = float(pose_min_track)
        self.hands_max_num = int(hands_max_num)
        self.hands_min_det = float(hands_min_det)
        self.hands_min_track = float(hands_min_track)
        self.verbose = bool(verbose)

        # קצב פרסום
        try:
            hz = float(publish_hz)
            self._publish_period_ms = max(10.0, 1000.0 / max(1.0, hz))
        except Exception:
            self._publish_period_ms = 1000.0 / 12.0
        self._last_publish_ms = 0.0

        # אובייקטים פנימיים
        self._mp = None
        self._pose = None
        self._hands = None
        self._ok_pose = False
        self._ok_hands = False
        self._opened = False
        self._frame_idx = 0

        # דיאגנוסטיקה
        self._diag: Dict[str, Any] = {"steps": [], "python": sys.version.split()[0]}
        self._last_error: Optional[str] = None

    # ----- מאפיינים -----
    @property
    def available(self) -> bool:
        return (self.enable_pose and self._ok_pose) or (self.enable_hands and self._ok_hands)

    @property
    def diagnostics(self) -> Dict[str, Any]:
        return dict(self._diag)

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def is_open(self) -> bool:
        return self._opened

    # ----- עזר -----
    def _fail(self, where: str, exc: Exception) -> None:
        tr = traceback.format_exc()
        self._last_error = f"{where}: {exc}\nTRACE:\n{tr}"
        LOG("error", self._last_error)
        self._diag["steps"].append(f"{where}:FAIL")

    # ----- open/close -----
    def start(self) -> "MediaPipeRunner":
        self.open(); return self

    def open(self) -> None:
        if self._opened: return
        # numpy (בדיקת זמינות בלבד)
        try:
            import numpy as np  # noqa
            self._diag["numpy"] = getattr(np, "__version__", None)
            self._diag["steps"].append("numpy:OK")
        except Exception as e:
            self._fail("import numpy", e); return

        # mediapipe
        try:
            import mediapipe as mp
            self._mp = mp
            self._diag["mediapipe"] = getattr(mp, "__version__", None)
            self._diag["mediapipe_path"] = getattr(mp, "__file__", None)
            self._diag["steps"].append("mediapipe:OK")
        except Exception as e:
            self._fail("import mediapipe", e); return

        # pose
        self._ok_pose = False; self._pose = None
        if self.enable_pose:
            try:
                self._pose = self._mp.solutions.pose.Pose(
                    static_image_mode=False,
                    model_complexity=self.pose_model_complexity,
                    enable_segmentation=False,
                    min_detection_confidence=self.pose_min_det,
                    min_tracking_confidence=self.pose_min_track,
                )
                self._ok_pose = True
                self._diag["steps"].append("pose:OK")
            except Exception as e:
                self._ok_pose = False; self._pose = None
                self._fail("create pose", e)

        # hands
        self._ok_hands = False; self._hands = None
        if self.enable_hands:
            try:
                self._hands = self._mp.solutions.hands.Hands(
                    static_image_mode=False,
                    max_num_hands=self.hands_max_num,
                    min_detection_confidence=self.hands_min_det,
                    min_tracking_confidence=self.hands_min_track,
                )
                self._ok_hands = True
                self._diag["steps"].append("hands:OK")
            except Exception as e:
                self._ok_hands = False; self._hands = None
                self._fail("create hands", e)

        self._opened = True
        if self.available and self.verbose:
            LOG("info", f"MediaPipe ready (pose={self._ok_pose}, hands={self._ok_hands}) | mp={self._diag.get('mediapipe')}")
            LOG("debug", f"mp_path={self._diag.get('mediapipe_path')}")
        if not self.available:
            LOG("warning", f"MediaPipe unavailable — Steps={self._diag.get('steps')}")

    def close(self) -> None:
        if not self._opened: return
        try:
            if self._pose: self._pose.close()
        except Exception: pass
        try:
            if self._hands: self._hands.close()
        except Exception: pass
        self._pose = self._hands = None
        self._ok_pose = self._ok_hands = False
        self._opened = False

    def __enter__(self) -> "MediaPipeRunner":
        self.open(); return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ----- עיבוד פריים (RGB בלבד) + פרסום JSON -----
    def process(self, frame_rgb) -> Tuple[Optional[object], Optional[object]]:
        """
        קלט: frame_rgb = np.ndarray (H,W,3, uint8) בפורמט RGB!
        פלט: (pose_results, hands_results) או (None, None).
        תופעת לוואי: פרסום JSON ל-state (set_last_pose) בקצב מוגבל.
        """
        if frame_rgb is None or not self.is_open: return None, None
        if not self.available: return None, None
        try:
            rgb = frame_rgb  # מגיע RGB כבר מה-main (המרה נעשית שם)
            pose = self._pose.process(rgb) if (self.enable_pose and self._ok_pose and self._pose) else None

            hands = None
            if self.enable_hands and self._ok_hands and self._hands and (self._frame_idx % self.hands_every_n == 0):
                hands = self._hands.process(rgb)
            self._frame_idx += 1

            # פרסום JSON בקצב מוגבל
            now_ms = time.time() * 1000.0
            if (now_ms - self._last_publish_ms) >= self._publish_period_ms:
                try:
                    h, w = (rgb.shape[0], rgb.shape[1]) if hasattr(rgb, "shape") else (0, 0)
                    payload: Dict[str, Any] = {"ok": False, "w": int(w), "h": int(h)}

                    # Pose
                    if pose and getattr(pose, "pose_landmarks", None) and hasattr(pose.pose_landmarks, "landmark"):
                        lm = pose.pose_landmarks.landmark
                        def xyv(i: int) -> Dict[str, float]:
                            p = lm[i]
                            return {"x": float(p.x) * w, "y": float(p.y) * h, "v": float(getattr(p, "visibility", 1.0))}
                        P = type("P", (), dict(
                            NOSE=0, L_EYE=2, R_EYE=5, L_EAR=7, R_EAR=8, L_SH=11, R_SH=12,
                            L_EL=13, R_EL=14, L_WR=15, R_WR=16, L_HIP=23, R_HIP=24,
                            L_KNEE=25, R_KNEE=26, L_ANK=27, R_ANK=28, L_HEEL=29, R_HEEL=30,
                            L_TOE=31, R_TOE=32
                        ))
                        payload["pose"] = {
                            "NOSE": xyv(P.NOSE),
                            "L_EYE": xyv(P.L_EYE), "R_EYE": xyv(P.R_EYE),
                            "L_EAR": xyv(P.L_EAR), "R_EAR": xyv(P.R_EAR),
                            "L_SH": xyv(P.L_SH), "R_SH": xyv(P.R_SH),
                            "L_EL": xyv(P.L_EL), "R_EL": xyv(P.R_EL),
                            "L_WR": xyv(P.L_WR), "R_WR": xyv(P.R_WR),
                            "L_HIP": xyv(P.L_HIP), "R_HIP": xyv(P.R_HIP),
                            "L_KNEE": xyv(P.L_KNEE), "R_KNEE": xyv(P.R_KNEE),
                            "L_ANK": xyv(P.L_ANK), "R_ANK": xyv(P.R_ANK),
                            "L_HEEL": xyv(P.L_HEEL), "R_HEEL": xyv(P.R_HEEL),
                            "L_TOE": xyv(P.L_TOE), "R_TOE": xyv(P.R_TOE),
                        }
                        payload["ok"] = True

                    # Hands
                    hands_arr = []
                    if hands and getattr(hands, "multi_hand_landmarks", None):
                        for hlm in hands.multi_hand_landmarks:
                            pts = []
                            for i in range(21):
                                p = hlm.landmark[i]
                                pts.append({"x": float(p.x) * w, "y": float(p.y) * h})
                            hands_arr.append(pts)
                    if hands_arr:
                        payload["hands"] = hands_arr

                    # HUD בסיסי (אופציונלי)
                    payload["hud"] = {"view": "Front", "conf": 0.85, "qs": 90}

                    # פרסום ל-state
                    try:
                        from admin_web.state import set_last_pose  # type: ignore
                        set_last_pose(payload)
                    except Exception:
                        pass
                finally:
                    self._last_publish_ms = now_ms

            return pose, hands

        except Exception as e:
            self._fail("process", e)
            return None, None
