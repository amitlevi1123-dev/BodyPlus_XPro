# -------------------------------------------------------
# ✋ מודול מדידות ידיים ואחיזה
#
# פונקציות:
#  - grip_state_from_hands(results_hands)
#  - wrist_angles(pixels) → (flex_L, flex_R, radul_L, radul_R) [deg]
#  - hand_orientation(results_hands, hand)
#  - he(v)
#  - publish_wrist_to_payload(pixels, payload, *, quality=None, include_radul=True)  ← חדש
#
# שדרוגים:
#  1) אפס נייטרלי דינמי (auto-zero) לשורש כף היד עם EMA פנימי (ללא שינוי API).
#  2) קלמפ זוויות: flex/extend ∈ [-90°, +90°], radial/ulnar ∈ [-45°, +45°].
#  3) כיוון סימן עקבי: כיפוף קדמי = חיובי; סטייה רדיאלית חיובית לכיוון האגודל.
#  4) פונקציית publish_* להזנת המפתחות שה־UI/שלד מצפה להם בפיילוד.
# -------------------------------------------------------

from __future__ import annotations
from typing import Optional, Tuple, Dict

import numpy as np

from ..geometry import vec, vector_vs_vertical, vector_vs_horizontal, safe_deg
from .pose_points import P


def grip_state_from_hands(results_hands) -> Tuple[Optional[str], Optional[str]]:
    """
    קובע את מצב האחיזה (פרונציה/סופינציה/ניטרלי) לכל יד.
    החישוב מתבסס על מיקום האגודל ביחס לאצבע המורה בציר ה־X.
    """
    left, right = None, None
    if not (results_hands and getattr(results_hands, "multi_handedness", None)
            and getattr(results_hands, "multi_hand_landmarks", None)):
        return left, right

    try:
        count = min(len(results_hands.multi_handedness), len(results_hands.multi_hand_landmarks))
        for i in range(count):
            handed = results_hands.multi_handedness[i]
            hlm = results_hands.multi_hand_landmarks[i]
            label = handed.classification[0].label.lower()  # 'left' או 'right'

            index_tip = hlm.landmark[8]   # קצה אצבע מורה
            thumb_tip = hlm.landmark[4]   # קצה אגודל

            # קביעה לפי מיקום יחסי
            if abs(index_tip.x - thumb_tip.x) < 0.02:
                state = "neutral"
            elif (thumb_tip.x < index_tip.x and label == "right") or (thumb_tip.x > index_tip.x and label == "left"):
                state = "pronated"
            else:
                state = "supinated"

            if label == "left":
                left = state
            else:
                right = state
    except Exception:
        pass

    return left, right


# ------------------------------- Auto-Zero & Helpers -------------------------------

class _NeutralOffsets:
    """
    שומר קיזוז נייטרלי (offset) לכל יד ומעדכן ב-EMA כאשר הזוויות נראות 'קרובות לנייטרל'.
    זה מאפשר שתנוחת מנוחה תציג ~0° גם אם יש היסט עקבי במדידה.
    """
    def __init__(self, alpha: float = 0.15):
        self.alpha = float(alpha)
        self.flex_L = 0.0
        self.flex_R = 0.0
        self.radul_L = 0.0
        self.radul_R = 0.0
        # ספים להגדרת "נייטרל" למדגם עדכון
        self._flex_neutral_thr = 15.0   # deg
        self._radul_neutral_thr = 12.0  # deg

    def _ema(self, prev: float, new: float) -> float:
        a = self.alpha
        return (1.0 - a) * prev + a * new

    def update_if_neutral(self, side: str, flex_raw: Optional[float], radul_raw: Optional[float]) -> None:
        if flex_raw is None or radul_raw is None:
            return
        if abs(flex_raw) <= self._flex_neutral_thr and abs(radul_raw) <= self._radul_neutral_thr:
            if side == "left":
                self.flex_L = self._ema(self.flex_L, float(flex_raw))
                self.radul_L = self._ema(self.radul_L, float(radul_raw))
            else:
                self.flex_R = self._ema(self.flex_R, float(flex_raw))
                self.radul_R = self._ema(self.radul_R, float(radul_raw))

    def apply(self, side: str, flex_raw: Optional[float], radul_raw: Optional[float]) -> Tuple[Optional[float], Optional[float]]:
        if flex_raw is None and radul_raw is None:
            return None, None
        if side == "left":
            f = None if flex_raw is None else float(flex_raw) - self.flex_L
            r = None if radul_raw is None else float(radul_raw) - self.radul_L
            return f, r
        else:
            f = None if flex_raw is None else float(flex_raw) - self.flex_R
            r = None if radul_raw is None else float(radul_raw) - self.radul_R
            return f, r


_neutral = _NeutralOffsets(alpha=0.15)


def _clamp(v: Optional[float], lo: float, hi: float) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(np.clip(float(v), lo, hi))
    except Exception:
        return None


# ------------------------------- Wrist Angles -------------------------------

def wrist_angles(pixels: Dict[str, Optional[Tuple[float, float]]]) -> Tuple[
    Optional[float], Optional[float], Optional[float], Optional[float]]:
    """
    מחשב זוויות בסיסיות בשורש כף היד:
      - כיפוף/פשיטה (flex/extend) מול הציר האנכי (Y).
      - סטייה רדיאלית/אולנרית (radial/ulnar) מול הציר האופקי (X).
    מחזיר: (flex_L, flex_R, radul_L, radul_R) במעלות — לאחר קיזוז נייטרלי וקלמפ.
    """
    out_flex_L = out_flex_R = out_radul_L = out_radul_R = None

    def wrist_vecs(side: str):
        w = P(pixels, f"{side}_wrist")
        idx = P(pixels, f"{side}_index")
        pnk = P(pixels, f"{side}_pinky")
        return w, idx, pnk

    for side, is_left in (("left", True), ("right", False)):
        w, idx, pnk = wrist_vecs(side)

        # --- RAW FLEX/EXT ---
        # משתמשים בוקטור Index→Wrist כדי שכאשר כף היד נייטרלית הערך יתקרב ל-0°.
        flex_raw = None
        if w and idx:
            v_flex = vec(idx, w)  # NB: כיוון הפוך מהרגיל כדי לתקן היסט סימן
            flex_raw = safe_deg(vector_vs_vertical(v_flex, signed=True))

        # --- RAW RADIAL/ULNAR ---
        radul_raw = None
        if w and idx and pnk:
            # ההפרש בין הכיוונים Wrist→Index ו-Wrist→Pinky יוצר וקטור "סטייה" רוחבית
            v_rad = vec(w, idx) - vec(w, pnk)
            radul_raw = safe_deg(vector_vs_horizontal(v_rad, signed=True))

        # עדכון offset אם המדידה "נראית נייטרלית"
        _neutral.update_if_neutral(side, flex_raw, radul_raw)

        # החלת offset להשגת אפס דינמי
        flex_adj, radul_adj = _neutral.apply(side, flex_raw, radul_raw)

        # קלמפ לתחומים סבירים להצגה
        flex_adj = _clamp(flex_adj, -90.0, +90.0)
        radul_adj = _clamp(radul_adj, -45.0, +45.0)

        if is_left:
            out_flex_L, out_radul_L = flex_adj, radul_adj
        else:
            out_flex_R, out_radul_R = flex_adj, radul_adj

    return out_flex_L, out_flex_R, out_radul_L, out_radul_R


def hand_orientation(results_hands, hand: str) -> str:
    """
    קובע כיוון כללי של כף היד לפי עומק (Z).
    """
    try:
        if not (results_hands and getattr(results_hands, "multi_handedness", None)
                and getattr(results_hands, "multi_hand_landmarks", None)):
            return "no_measure"

        count = min(len(results_hands.multi_handedness), len(results_hands.multi_hand_landmarks))
        for i in range(count):
            handed = results_hands.multi_handedness[i].classification[0].label.lower()
            if handed != hand:
                continue

            lms = results_hands.multi_hand_landmarks[i].landmark
            idxs = [0, 1, 5, 9, 13, 17]  # שורש כף יד + MCPs
            avg_z = sum(float(lms[j].z) for j in idxs) / len(idxs)

            THR = 0.025
            if avg_z < -THR:
                return "supination"
            if avg_z > THR:
                return "pronation"
            return "neutral"

        return "no_measure"
    except Exception:
        return "no_measure"


def he(v: str) -> str:
    """תרגום של ערכי orientation לעברית (להצגה בלוח ניהול)."""
    return {
        "supination": "סופינציה",
        "pronation": "פרונציה",
        "neutral": "ניטרלי",
        "no_measure": "אין מדידה",
    }.get(v, "אין מדידה")


# ------------------------------- NEW: publish to payload -------------------------------

def _as_quality(q: Optional[float]) -> float:
    try:
        qf = float(q)
        if not (0.0 <= qf <= 1.0):
            return 1.0
        return qf
    except Exception:
        return 1.0


def publish_wrist_to_payload(
    pixels: Dict[str, Optional[Tuple[float, float]]],
    payload, *,
    quality: Optional[Dict[str, float]] = None,
    include_radul: bool = True
) -> None:
    """
    מזרים את מדידות שורש כף היד לפיילוד במפתחות שהשלד/UX מצפה להם:
      - wrist_flex_ext_left_deg, wrist_flex_ext_right_deg
      - (אופציונלי) wrist_radul_left_deg, wrist_radul_right_deg

    Args:
        pixels: מילון נקודות 2D (שם→(x,y)) כמו בשאר המודולים.
        payload: אובייקט Payload (עם המתודה .measure()).
        quality: dict אופציונלי של איכות [0..1] לכל ערוץ: {"flex_L":0.9,"flex_R":0.85,"radul_L":0.8,"radul_R":0.8}
        include_radul: אם False — לא כותבים סטייה רדיאלית/אולנרית.

    אין חריגות; אם ערך חסר/לא תקין → יסומן missing ע"י ה־Payload.
    """
    try:
        flex_L, flex_R, radul_L, radul_R = wrist_angles(pixels)

        q_map = quality or {}
        q_flex_L = _as_quality(q_map.get("flex_L"))
        q_flex_R = _as_quality(q_map.get("flex_R"))
        q_radul_L = _as_quality(q_map.get("radul_L"))
        q_radul_R = _as_quality(q_map.get("radul_R"))

        # כיפוף/פשיטה — מפתחות חובה שהשלד קורא
        payload.measure("wrist_flex_ext_left_deg",  flex_L, quality=q_flex_L, source="hands", unit="deg")
        payload.measure("wrist_flex_ext_right_deg", flex_R, quality=q_flex_R, source="hands", unit="deg")

        # אופציונלי: סטייה רדיאלית/אולנרית
        if include_radul:
            payload.measure("wrist_radul_left_deg",  radul_L, quality=q_radul_L, source="hands", unit="deg")
            payload.measure("wrist_radul_right_deg", radul_R, quality=q_radul_R, source="hands", unit="deg")

    except Exception as e:
        # לא מפילים את הזרימה על מדידה נקודתית
        try:
            payload.add_note(f"hands.publish_wrist_to_payload: {type(e).__name__}")
        except Exception:
            pass
