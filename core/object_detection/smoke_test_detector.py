# core/object_detection/smoke_test_detector.py
# -----------------------------------------------------------------------------
# בדיקת עשן "יבשה" (ללא מצלמה וללא מודל):
# - מסמלצת דאמבל שנע וזווית שמשתנה.
# - מעביר דרך Tracker + FeatureAugmentor.
# - וידוא: אין "קפיצות", angle_stale True רק כשחסר רגעית.
# -----------------------------------------------------------------------------

from __future__ import annotations
import time
from typing import Any, Dict, List, Tuple

# ייבוא לפי ה־API שב-engine משתמש:
from .tracks import TrackerConfig, Tracker, Obs
from .features import FeatureConfig, FeatureAugmentor


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_payload_like_engine(tracks: List[Any], ts_ms: int) -> Dict[str, Any]:
    """בניית payload דומה ל-engine לצורך הדפסה/בדיקה."""
    objects = []
    for t in tracks:
        # תמיכה גם באובייקט וגם ב-dict
        def get(field, default=None):
            return getattr(t, field, default) if hasattr(t, field) else (
                t.get(field, default) if isinstance(t, dict) else default)

        objects.append({
            "track_id": get("track_id", get("id", None)),
            "label": get("label", None),
            "score": get("score", None),
            "box": get("box", None),
            "state": get("state", None),
            "angle_deg": get("angle_deg", None),
            "angle_stale": get("angle_stale", False),
            "quality": get("angle_quality", get("quality", None)),
            "ang_src": get("angle_src", None),
            "updated_at_ms": ts_ms,
        })
    return {"objects": objects, "ts_ms": ts_ms}


def main():
    W, H = 1280, 720  # לא בשימוש כרגע, שמור לשינויים עתידיים
    tracker = Tracker(TrackerConfig())
    feats = FeatureAugmentor(FeatureConfig(
        angle_grace_frames=3,
        trail_enabled=True
    ))

    x1, y1, w, h = 600, 400, 80, 40
    angle = 10.0

    for i in range(30):
        ts_ms = _now_ms()

        # בכוונה "מאבדים" זווית לפעמים כדי לבדוק angle_stale/חנינה
        ang = angle if i % 7 != 0 else None
        ang_quality = 0.8 if ang is not None else 0.2
        ang_src = "sim"

        obs_list = [
            Obs(
                label="dumbbell",
                score=0.90,
                box=(int(x1), int(y1), int(x1 + w), int(y1 + h)),
                angle_deg=ang,
                angle_quality=ang_quality,
                angle_src=ang_src,
            )
        ]

        # עדכון מסלול
        tracks = tracker.update(obs_list, ts_ms=ts_ms)

        # פיצ'רים (עשויים לעדכן tracks במקום או להחזיר רשימה חדשה)
        tracks = feats.apply(tracks, ts_ms=ts_ms) or tracks

        # בניית payload לצורך הדפסה (בד"כ engine עושה זאת)
        payload = _build_payload_like_engine(tracks, ts_ms=ts_ms)

        if payload["objects"]:
            o = payload["objects"][0]
            print(
                f"frame={i:02d} id={o['track_id']} state={o['state']} "
                f"stale={o.get('angle_stale', False)} box={o['box']} "
                f"angle={o.get('angle_deg')} score={o.get('score', 0):.2f}"
            )
        else:
            print(f"frame={i:02d} no objects")

        # עדכון מיקום/זווית לסימולציה
        x1 += 6
        y1 -= 2
        angle = (angle + 3.5) % 180

        time.sleep(0.03)

    print("Smoke test done.")


if __name__ == "__main__":
    main()
