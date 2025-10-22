# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# exercise_engine/segmenter/set_counter.py
# מנגנון ספירת סטים אוטומטי (rep_event + timeout) + תמיכה ב-set.begin/set.end
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Optional, Dict, Any

__all__ = ["SETS", "SetCounter"]

class SetCounter:
    """
    מנגנון ספירת סטים עבור תרגילים.
    - ניהול סטים: התחלה, סיום, חישוב זמן ומונה חזרות.
    - תמיכה בטריגרים חיצוניים (set.begin / set.end) ובסגירה אוטומטית לפי timeout.
    - סט שנגמר בכפייה (forced=True) נחשב תקין גם אם לא הושג min_reps.
    """

    def __init__(self, *, min_reps: int = 1, reset_timeout_s: float = 7.0) -> None:
        """
        :param min_reps: מינ' חזרות לסט תקין
        :param reset_timeout_s: פרק זמן (בשניות) ללא חזרה עד סגירת סט אוטומטית
        """
        self.min_reps = int(min_reps)
        self.reset_timeout_ms = int(reset_timeout_s * 1000.0)
        self.active = False
        self.index = 0
        self.reps_in_set = 0
        self.last_rep_ts: Optional[int] = None
        self.start_ts: Optional[int] = None
        self.end_ts: Optional[int] = None
        self.total_completed: int = 0
        self.last_summary: Optional[Dict[str, Any]] = None

    # --------- ניהול מצב ---------
    def reset_state(self) -> None:
        """איפוס מלא של מונה הסטים (לשימוש בבדיקות/אתחול)."""
        self.active = False
        self.index = 0
        self.reps_in_set = 0
        self.last_rep_ts = None
        self.start_ts = None
        self.end_ts = None
        self.total_completed = 0
        self.last_summary = None

    # --------- מחזור סט ---------
    def begin_set(self, now_ms: int) -> None:
        """מתחיל סט חדש (אם אין סט פעיל)."""
        if not self.active:
            self.active = True
            self.index += 1
            self.reps_in_set = 0
            self.start_ts = now_ms
            self.end_ts = None
            self.last_rep_ts = None

    def end_set(self, now_ms: int, *, forced: bool = False) -> Optional[Dict[str, Any]]:
        """מסיים סט פעיל ומחזיר סיכום; אם אין סט פעיל — מחזיר None."""
        if not self.active:
            return None

        self.end_ts = now_ms
        reps = int(self.reps_in_set)
        duration_s = round(((self.end_ts or now_ms) - (self.start_ts or now_ms)) / 1000.0, 3) if self.start_ts else 0.0

        ok = (reps >= self.min_reps) or forced
        summary = {
            "set_index": int(self.index),
            "reps": reps,
            "duration_s": float(duration_s),
            "ok": bool(ok),
            "forced": bool(forced),
            "start_ts": int(self.start_ts or now_ms),
            "end_ts": int(self.end_ts or now_ms),
        }

        self.last_summary = summary
        if ok:
            self.total_completed += 1

        # reset לפעם הבאה
        self.active = False
        self.reps_in_set = 0
        self.start_ts = None
        self.end_ts = None
        self.last_rep_ts = None

        return summary

    # --------- עדכון מריצות ---------
    def update(self, rep_event: Optional[Dict[str, Any]], now_ms: int) -> Optional[Dict[str, Any]]:
        """
        עדכון לפי rep_event (חזרה שנספרה) או סגירה אוטומטית לפי timeout.
        :return: summary אם סט נסגר אוטומטית, אחרת None
        """
        # יש חזרה חדשה
        if rep_event:
            if not self.active:
                self.begin_set(now_ms)
            self.reps_in_set += 1
            self.last_rep_ts = now_ms
            return None

        # אין חזרה חדשה: בדוק timeout אם יש סט פעיל
        if self.active:
            # אם עדיין אין last_rep_ts, נחשב את ה־idle מאז start_ts כדי לא "לתקוע" סטים ללא חזרות
            ref_ts = self.last_rep_ts if self.last_rep_ts is not None else self.start_ts
            if ref_ts is not None and (now_ms - int(ref_ts)) >= self.reset_timeout_ms:
                return self.end_set(now_ms, forced=False)

        return None

    # --------- טריגרים חיצוניים ---------
    def handle_signals(self, raw_metrics: Dict[str, Any], now_ms: int) -> Optional[Dict[str, Any]]:
        """
        תגובה ל־set.begin / set.end מה־raw.
        :return: summary אם נסגר סט בעקבות set.end, אחרת None
        """
        closed = None
        if bool(raw_metrics.get("set.begin")):
            self.begin_set(now_ms)
        if bool(raw_metrics.get("set.end")):
            closed = self.end_set(now_ms, forced=True)
        return closed

    # --------- הזרקה לדוח ---------
    def inject(self, target: Dict[str, Any]) -> None:
        """
        הזרקת סטטוס הסטים לשדות rep.* בתוך דוח/קאנוניקל.
        """
        target["rep.set_active"] = bool(self.active)
        target["rep.set_index"]  = int(self.index)
        target["rep.set_reps"]   = int(self.reps_in_set)
        target["rep.set_total"]  = int(self.total_completed)

        if self.last_summary:
            target.setdefault("rep.set_last_ok", bool(self.last_summary.get("ok")))
            target.setdefault("rep.set_last_reps", int(self.last_summary.get("reps", 0)))
            target.setdefault("rep.set_last_duration_s", float(self.last_summary.get("duration_s", 0.0)))

# אינסטנס יחיד לשימוש גלובלי בריצה
SETS = SetCounter()
