# core/object_detection/simdet.py
# ---------------------------------------------------------------------------
# BodyPlus XPro — Simulated Object Detector
#
# מה הקובץ עושה:
# • מחזיר זיהוי מדומה של barbell ו-dumbbell בתנועה מחזורית (sin/cos)
# • משמש לבדיקה של צנרת המערכת גם בלי מודל אמיתי או מצלמה
# ---------------------------------------------------------------------------

from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


# -----------------------------
# Data Models
# -----------------------------

@dataclass
class DetectionItem:
    label: str
    bbox: Tuple[int, int, int, int]   # (x, y, w, h)
    conf: float
    id: Optional[int] = None


@dataclass
class DetectorState:
    ok: bool
    provider: str
    err: Optional[str] = None
    latency_ms: Optional[float] = None


# -----------------------------
# Simulator
# -----------------------------

class SimDetector:
    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.provider = "sim"
        self.t0 = time.time()

    def detect(self, frame_bgr: Any = None, ts_ms: Optional[int] = None) -> Dict[str, Any]:
        """מחזיר תוצאה מדומה עם שני אובייקטים בתנועה מחזורית."""
        t = time.time() - self.t0
        w, h = 1280, 720

        # יצירת מיקומים משתנים בזמן
        x1 = int(200 + 100 * math.sin(t))
        y1 = 300
        x2 = int(800 + 120 * math.cos(t))
        y2 = 400

        objects: List[DetectionItem] = [
            DetectionItem("barbell", (x1, y1, 120, 80), 0.95, id=1),
            DetectionItem("dumbbell", (x2, y2, 80, 60), 0.92, id=2),
        ]

        result: Dict[str, Any] = {
            "frame": {"w": w, "h": h, "ts_ms": int(time.time() * 1000)},
            "objects": [o.__dict__ for o in objects],
            "detector_state": {
                "ok": True,
                "provider": self.provider,
                "latency_ms": 10.0
            },
            "tracks": []
        }
        return result


if __name__ == "__main__":
    import json
    det = SimDetector({})
    out = det.detect()
    print(json.dumps(out, ensure_ascii=False))
