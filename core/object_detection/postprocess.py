# -*- coding: utf-8 -*-
# ===============================================================
# postprocess.py — שכבת פוסט-פרוסס לזיהוי חפצים (BodyPlus_XPro)
# מה הקובץ עושה:
# 1) מוודא שתוויות תואמות ל-weights ע"י class_id -> label בטוח.
# 2) אופציונלי: "רמזי צורה" (shape hints) לטיוב barbell/dumbbell.
#
# שימוש:
#   from core.object_detection.postprocess import process_detections
#   dets = process_detections(dets, use_shape_hints=True)
#
# פורמט expected לכל detection (dict):
# {
#   "class_id": int,            # אינדקס מהמודל (0/1/…)
#   "label": str | None,        # ימולא לפי המפה הבטוחה
#   "score": float,             # 0..1
#   "x1": float, "y1": float, "x2": float, "y2": float
# }
# ===============================================================

from __future__ import annotations
from typing import List, Dict, Any, Optional, Tuple

# ---- מפת מחלקות ברירת-מחדל (תואמת ל-weights) ----
# 0 = dumbbell, 1 = barbell
DEFAULT_CLASS_INDEX_MAP: Dict[int, str] = {
    0: "dumbbell",
    1: "barbell",
}

# ---- פרמטרים רכים לברירות מחדל ----
_ASPECT_BAR_LONG = 2.2        # יחס רוחב/גובה שמאפיין barbell
_ASPECT_DB_SQUARISH = 1.6     # יחס שמאפיין dumbbell כ"מרובע" יותר
_DEFAULT_BOOST = 0.12
_DEFAULT_PENALTY = 0.10
_DEFAULT_IOU_RESOLVE = 0.60
_MIN_BOX_SIDE = 1.0

# ---- לוגינג עדין (נופל ל-print אם loguru לא מותקן) ----
try:
    from loguru import logger
except Exception:  # pragma: no cover
    class _FallbackLogger:
        def info(self, *a, **k): print(*a)
        def debug(self, *a, **k): print(*a)
        def warning(self, *a, **k): print(*a)
        def error(self, *a, **k): print(*a)
    logger = _FallbackLogger()  # type: ignore


# ---------------- Utilities ----------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v

def _fix_box_coords(d: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """מוודא x1<=x2, y1<=y2 וגודל מינימלי; מחזיר תיבה תקינה או None."""
    try:
        x1 = float(d.get("x1", 0.0)); y1 = float(d.get("y1", 0.0))
        x2 = float(d.get("x2", 0.0)); y2 = float(d.get("y2", 0.0))
    except Exception:
        return None
    # החלפה במקרה הפוך
    if x2 < x1: x1, x2 = x2, x1
    if y2 < y1: y1, y2 = y2, y1
    # מינימום צד
    if (x2 - x1) < _MIN_BOX_SIDE or (y2 - y1) < _MIN_BOX_SIDE:
        return None
    return (x1, y1, x2, y2)

def _apply_label_index_map(dets: List[Dict[str, Any]],
                           index_map: Dict[int, str]) -> None:
    """מעדכן det['label'] לפי det['class_id'] דרך המפה הבטוחה, in-place."""
    for d in dets:
        cid = d.get("class_id", None)
        if isinstance(cid, (int, float)):
            cid = int(cid)
            if cid in index_map:
                d["label"] = index_map[cid]

def _shape_hint_label(w: float, h: float) -> Optional[str]:
    """מחזיר 'barbell' אם התיבה מאורכת מאד, 'dumbbell' אם קומפקטית, אחרת None."""
    if w <= 0 or h <= 0:
        return None
    ar = w / h
    if ar >= _ASPECT_BAR_LONG:
        return "barbell"
    if ar <= _ASPECT_DB_SQUARISH:
        return "dumbbell"
    return None

def _iou(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    ix1 = max(a["x1"], b["x1"]); iy1 = max(a["y1"], b["y1"])
    ix2 = min(a["x2"], b["x2"]); iy2 = min(a["y2"], b["y2"])
    iw = max(ix2 - ix1, 0.0); ih = max(iy2 - iy1, 0.0)
    inter = iw * ih
    if inter <= 0: return 0.0
    area_a = max((a["x2"] - a["x1"]) * (a["y2"] - a["y1"]), 1e-9)
    area_b = max((b["x2"] - b["x1"]) * (b["y2"] - b["y1"]), 1e-9)
    denom = max(area_a + area_b - inter, 1e-9)
    return inter / denom


# ---------------- Core ----------------

def _refine_barbell_dumbbell(
    dets: List[Dict[str, Any]],
    *,
    boost: float,
    penalty: float,
    iou_resolve_th: float,
) -> List[Dict[str, Any]]:
    """משפר סיווג barbell/dumbbell על סמך צורת התיבה וחפיפות בין-מחלקתיות."""
    # 1) תיקון ציונים לפי צורה
    for d in dets:
        box = _fix_box_coords(d)
        if box is None:
            d["_drop"] = True
            continue
        x1, y1, x2, y2 = box
        d["x1"], d["y1"], d["x2"], d["y2"] = x1, y1, x2, y2
        w = x2 - x1; h = y2 - y1
        hint = _shape_hint_label(w, h)
        # clamp score
        d["score"] = _clamp(float(d.get("score", 0.0)), 0.0, 1.0)
        try:
            if hint == d.get("label"):
                d["score"] = _clamp(d["score"] + float(boost), 0.0, 0.999)
                logger.debug(f"[POST] {str(d.get('label','?')).upper()}: +{float(boost):.2f} (shape)")
            elif hint is not None and hint != d.get("label"):
                d["score"] = _clamp(d["score"] - float(penalty), 0.0, 1.0)
                logger.debug(f"[POST] {str(d.get('label','?')).upper()}: -{float(penalty):.2f} (shape-mismatch)")
        except Exception:
            # לא מפיל זרימה אם חסר שדה
            pass

    # הסר מסומנים-למחיקה (קופסאות לא חוקיות)
    dets = [d for d in dets if not d.get("_drop")]

    # 2) פתרון התנגשויות בין-מחלקתיות
    keep: List[Dict[str, Any]] = []
    for d in sorted(dets, key=lambda x: (x.get("score", 0.0), x.get("label", "")), reverse=True):
        drop = False
        for k in keep:
            if d.get("label") != k.get("label") and _iou(d, k) >= iou_resolve_th:
                # הכרעה לפי התאמת צורה, אחרת שומרים את הגבוה (k)
                w1 = d["x2"] - d["x1"]; h1 = d["y2"] - d["y1"]
                w2 = k["x2"] - k["x1"]; h2 = k["y2"] - k["y1"]
                h1n = _shape_hint_label(w1, h1)
                h2n = _shape_hint_label(w2, h2)
                if h1n == d.get("label") and h2n != k.get("label"):
                    logger.debug(f"[POST] resolve: keep={d.get('label')} drop={k.get('label')} (shape)")
                    keep.remove(k); break
                else:
                    drop = True
                    logger.debug(f"[POST] resolve: keep={k.get('label')} drop={d.get('label')} (score/shape)")
                    break
        if not drop:
            keep.append(d)
    return keep


def process_detections(
    detections: List[Dict[str, Any]],
    *,
    use_shape_hints: bool = False,
    class_index_map: Optional[Dict[int, str]] = None,
    boost: float = _DEFAULT_BOOST,
    penalty: float = _DEFAULT_PENALTY,
    iou_resolve_th: float = _DEFAULT_IOU_RESOLVE,
) -> List[Dict[str, Any]]:
    """
    נקודת כניסה אחת מפושטת:
    1) class_id -> label לפי המפה הבטוחה (קלט יכול להגיע בלי label).
    2) אופציונלי: רמזי צורה לשיפור בין barbell/dumbbell.
    3) נירמול קופסאות וציונים.
    """
    if not detections:
        return detections

    # צילום "לפני" בשביל דיבוג קצר
    try:
        logger.debug(
            "[POST] in: n={} labels={} scores={}",
            len(detections),
            [d.get("label") for d in detections[:5]],
            [round(float(d.get("score", 0.0)), 3) for d in detections[:5]],
        )
    except Exception:
        pass

    # map class_id -> label (in-place)
    _apply_label_index_map(detections, class_index_map or DEFAULT_CLASS_INDEX_MAP)

    # נירמול קואורדינטות, הורדת תיבות לא-חוקיות, קלמפ ציונים
    normed: List[Dict[str, Any]] = []
    for d in detections:
        box = _fix_box_coords(d)
        if box is None:
            continue
        x1, y1, x2, y2 = box
        dd = dict(d)
        dd["x1"], dd["y1"], dd["x2"], dd["y2"] = x1, y1, x2, y2
        dd["score"] = _clamp(float(dd.get("score", 0.0)), 0.0, 1.0)
        # ודא תווית גם אם class_id לא במפה
        if not dd.get("label") and isinstance(dd.get("class_id"), (int, float)):
            dd["label"] = str(int(dd["class_id"]))
        normed.append(dd)

    # shape hints (אופציונלי)
    if use_shape_hints:
        normed = _refine_barbell_dumbbell(
            normed, boost=float(boost), penalty=float(penalty), iou_resolve_th=float(iou_resolve_th)
        )

    # מיון דטרמיניסטי קל: score ואז label
    normed.sort(key=lambda d: (d.get("score", 0.0), d.get("label", "")), reverse=True)

    # תקציר “אחרי”
    try:
        from collections import Counter
        c = Counter([d.get("label", "?") for d in normed])
        logger.debug(
            "[POST] out: n={} class_dist={} top={}",
            len(normed),
            dict(c),
            [(d.get("label"), round(d.get("score", 0.0), 3)) for d in normed[:5]],
        )
    except Exception:
        pass

    return normed
