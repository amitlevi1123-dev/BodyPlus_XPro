# =============================================================================
# 🇮🇱 MediaPipeRunner (Pose + Hands) עם אופציית Overlay פנימית
# I/O:
#   קלט : פריים BGR (numpy array)
#   פלט : tuple -> (results_pose, results_hands) או (None, None) במקרה כשל
# שימוש בסיסי:
#   mpr = MediaPipeRunner(enable_pose=True, enable_hands=True).start()
#   pose, hands = mpr.process(frame)
#   mpr.release()
#
# ציור Overlay מתוך הרץ (ללא שינוי חתימה):
#   from app.ui.video import get_streamer
#   mpr = MediaPipeRunner(enable_pose=True, enable_hands=True, overlay=True, overlay_hz=12).start()
#   mpr.set_overlay_sink(get_streamer().push_bgr_frame)  # דחיפה לווידאו (MJPEG)
#   pose, hands = mpr.process(frame)  # יצייר על עותק של frame בקצב מוגבל וידחוף ל-sink
# =============================================================================

from __future__ import annotations
from typing import Optional, Tuple, Dict, Any, Callable
import sys, traceback, time

# ---------- לוגים ----------
try:
    from core.logs import logger  # type: ignore
    def LOG(level: str, msg: str) -> None:
        getattr(logger, level, logger.info)(msg)
except Exception:
    def LOG(level: str, msg: str) -> None:
        print(f"[{level.upper()}] {msg}")

# Overlay (אופציונלי)
try:
    from app.vis.overlay import draw_overlay  # type: ignore
    _HAS_OVERLAY = True
except Exception:
    draw_overlay = None  # type: ignore
    _HAS_OVERLAY = False


class MediaPipeRunner:
    def __init__(
        self,
        *,
        # דגלים להפעלה/כיבוי מודולים
        enable_pose: bool = True,
        enable_hands: bool = True,

        # הגדרות עיבוד
        max_width: int = 720,
        hands_every_n: int = 1,

        # היפר־פרמטרים של Pose
        pose_model_complexity: int = 1,
        pose_min_det: float = 0.5,
        pose_min_track: float = 0.5,

        # היפר־פרמטרים של Hands
        hands_max_num: int = 2,
        hands_min_det: float = 0.5,
        hands_min_track: float = 0.5,

        # מבנה נתונים
        input_is_bgr: bool = True,
        verbose: bool = True,

        # ---------- NEW: Overlay ----------
        overlay: bool = False,           # לצייר overlay מתוך הרץ?
        overlay_hz: float = 12.0,        # קצב ציור/דחיפה מקסימלי
    ) -> None:
        # דגלים
        self.enable_pose = bool(enable_pose)
        self.enable_hands = bool(enable_hands)

        # פרמטרים כלליים
        self.max_width = int(max_width) if max_width else 0
        self.hands_every_n = max(1, int(hands_every_n))
        self.pose_model_complexity = int(pose_model_complexity)
        self.pose_min_det = float(pose_min_det)
        self.pose_min_track = float(pose_min_track)
        self.hands_max_num = int(hands_max_num)
        self.hands_min_det = float(hands_min_det)
        self.hands_min_track = float(hands_min_track)
        self.input_is_bgr = bool(input_is_bgr)
        self.verbose = bool(verbose)

        # Overlay params
        self.overlay_enabled = bool(overlay)
        try:
            hz = float(overlay_hz)
            self._overlay_period_ms = max(10.0, 1000.0 / max(1.0, hz))
        except Exception:
            self._overlay_period_ms = 1000.0 / 12.0
        self._last_overlay_ms = 0.0
        self._overlay_sink: Optional[Callable[[Any], None]] = None  # expects BGR image
        self._last_annotated = None  # לשימוש אופציונלי ע"י לקוח

        # אובייקטים פנימיים
        self._pose = None
        self._hands = None
        self._cv2 = None
        self._mp = None
        self._frame_idx = 0

        self._ok_pose = False
        self._ok_hands = False
        self._opened = False

        # דיאגנוסטיקה
        self._diag: Dict[str, Any] = {"steps": [], "python": sys.version.split()[0]}
        self._last_error: Optional[str] = None

    # ---------- מאפיינים ----------
    @property
    def available(self) -> bool:
        """לפחות אחד מהמודולים זמין/פועל."""
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

    def set_overlay_sink(self, sink: Optional[Callable[[Any], None]]) -> None:
        """
        קבע פונקציה שמקבלת BGR frame ומציגה/משדרת אותו (למשל: get_streamer().push_bgr_frame).
        """
        self._overlay_sink = sink

    def get_last_annotated(self):
        """הפריים המסומן האחרון (אם overlay פעיל)."""
        return self._last_annotated

    # ---------- עזר לכשל ----------
    def _fail(self, where: str, exc: Exception) -> None:
        tr = traceback.format_exc()
        self._last_error = f"{where}: {exc}\nTRACE:\n{tr}"
        LOG("error", self._last_error)
        self._diag["steps"].append(f"{where}:FAIL")

    # ---------- מחזור חיים ----------
    def start(self) -> "MediaPipeRunner":
        """פותח ומחזיר self לצורך chaining."""
        self.open()
        return self

    def release(self) -> None:
        """סוגר משאבים."""
        self.close()

    def open(self) -> None:
        if self._opened:
            return

        # 1) numpy
        try:
            import numpy as np  # noqa
            self._diag["numpy"] = getattr(np, "__version__", None)
            self._diag["steps"].append("numpy:OK")
        except Exception as e:
            self._fail("import numpy", e); return

        # 2) cv2
        try:
            import cv2
            self._cv2 = cv2
            self._diag["opencv"] = getattr(cv2, "__version__", None)
            self._diag["opencv_path"] = getattr(cv2, "__file__", None)
            self._diag["steps"].append("cv2:OK")
        except Exception as e:
            self._fail("import cv2", e); return

        # 3) mediapipe
        try:
            import mediapipe as mp
            self._mp = mp
            self._diag["mediapipe"] = getattr(mp, "__version__", None)
            self._diag["mediapipe_path"] = getattr(mp, "__file__", None)
            self._diag["steps"].append("mediapipe:OK")
        except Exception as e:
            self._fail("import mediapipe", e); return

        # 4) pose (אופציונלי)
        self._ok_pose = False
        self._pose = None
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

        # 5) hands (אופציונלי)
        self._ok_hands = False
        self._hands = None
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
            LOG("info",
                f"MediaPipe OK (pose={self._ok_pose}, hands={self._ok_hands}) | "
                f"py={self._diag.get('python')} np={self._diag.get('numpy')} "
                f"cv2={self._diag.get('opencv')} mp={self._diag.get('mediapipe')}"
            )
            LOG("debug",
                f"cv2_path={self._diag.get('opencv_path')} | mp_path={self._diag.get('mediapipe_path')}"
            )
        if not self.available:
            LOG("warning", f"MediaPipe unavailable — Steps={self._diag.get('steps')}")

    def close(self) -> None:
        if not self._opened:
            return
        try:
            if self._pose:
                self._pose.close()
        except Exception:
            pass
        try:
            if self._hands:
                self._hands.close()
        except Exception:
            pass
        self._pose = self._hands = None
        self._ok_pose = self._ok_hands = False
        self._opened = False

    def __enter__(self) -> "MediaPipeRunner":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ---------- עיבוד פריים + (אופציונלי) Overlay ----------
    def process(self, frame) -> Tuple[Optional[object], Optional[object]]:
        """
        מקבל פריים BGR ומחזיר (pose_results, hands_results).
        אם overlay פעיל — נצייר על עותק של הפריים ונדחוף ל-sink בקצב מוגבל.
        """
        if frame is None or not self.is_open:
            return None, None
        if not self.available:
            return None, None
        try:
            cv2 = self._cv2
            proc = frame
            if self.max_width and hasattr(proc, "shape") and proc.shape[1] > self.max_width:
                try:
                    scale = self.max_width / proc.shape[1]
                    proc = cv2.resize(proc, (self.max_width, int(proc.shape[0] * scale)), interpolation=cv2.INTER_AREA)
                except Exception:
                    proc = frame

            rgb = cv2.cvtColor(proc, cv2.COLOR_BGR2RGB) if self.input_is_bgr else proc

            pose = self._pose.process(rgb) if (self.enable_pose and self._ok_pose and self._pose) else None

            hands = None
            if self.enable_hands and self._ok_hands and self._hands and (self._frame_idx % self.hands_every_n == 0):
                hands = self._hands.process(rgb)

            self._frame_idx += 1

            # ----- Overlay (אופציונלי) -----
            if self.overlay_enabled and _HAS_OVERLAY:
                now_ms = time.time() * 1000.0
                if (now_ms - self._last_overlay_ms) >= self._overlay_period_ms:
                    try:
                        annotated = frame.copy()
                        hud = None  # אפשר להזריק HUD מהחוץ אם תרצה — השארתי פשוט
                        draw_overlay(annotated, pose, hands, hud=hud)
                        self._last_annotated = annotated
                        sink = self._overlay_sink
                        if callable(sink):
                            try:
                                sink(annotated)
                            except Exception:
                                pass
                        self._last_overlay_ms = now_ms
                    except Exception:
                        # לא מפיל — ממשיך רגיל
                        pass

            return pose, hands

        except Exception as e:
            self._fail("process", e)
            return None, None
