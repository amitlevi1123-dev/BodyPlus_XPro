# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# הסבר קצר (עברית):
# קובץ זה מרכז את מערכת האינדיקציות: יצירה (emit), דירוג חומרה, שמירת "האחרונים"
# (ring buffer קטן), Rate-limit בסיסי, וכתיבה ללוג באמצעות log_writer.
# קלטים מרכזיים: קריאות emit(type, severity?, message?, context?, tags?).
# פלט/תוצרים: רשימת אינדיקציות חיות (get_recent) + רישום לקובץ JSONL יומי.
# הערות: מודול זה מופרד מ-core/Main; עובד על אירועי מנוע בלבד; ידידותי ל-AI (שדות ברורים).
# -----------------------------------------------------------------------------

from __future__ import annotations
import time
import threading
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from . import log_writer

# תצורה בסיסית
RECENT_MAX = 200            # כמה אירועים לשמור בזיכרון לתצוגה חיה
RATE_LIMIT_WINDOW_S = 3.0   # חלון לזיהוי ספאם על אותו אירוע
DEFAULT_SEVERITY_BY_TYPE = {
    "reload_success": "info",
    "reload_failed": "error",
    "missing_required": "warn",
    "unscored_missing_critical": "error",
    "low_pose_confidence": "warn",
    "alias_conflict": "warn",
    "version_mismatch": "warn",
    "fps_drop": "warn",
    "latency_high": "warn",
    "no_exercise_selected": "info",
}

_lock = threading.RLock()
_recent: List[Dict[str, Any]] = []  # ring buffer ידני פשוט
# מפת Rate-limit: מפתח אירוע (type + context המהותי) → (last_ts, count)
_rl_map: Dict[str, Tuple[float, int]] = {}

@dataclass
class DiagEvent:
    time_ms: int
    type: str
    severity: str
    message: str
    context: Dict[str, Any]
    tags: List[str]
    library_version: Optional[str] = None
    payload_version: Optional[str] = None
    count: int = 1  # לכמות מאוחדת בחלון ה-RL

def _now_ms() -> int:
    return int(time.time() * 1000)

def _key_for_rl(ev_type: str, context: Dict[str, Any]) -> str:
    # בוחרים שדות מזהים כדי לאחד אירועים דומים (למשל על אותו criterion/exercise)
    crit = context.get("criterion") or ""
    ex = context.get("exercise") or ""
    miss = ",".join(sorted(map(str, context.get("missing", []) or [])))
    alias = ",".join(sorted(map(str, context.get("alias_keys", []) or [])))
    return f"{ev_type}|{ex}|{crit}|{miss}|{alias}"

def _apply_rate_limit(ev: DiagEvent) -> Optional[DiagEvent]:
    """מאחד אירועים זהים בחלון קצר. מחזיר אירוע לכתיבה/תצוגה, או None אם מאוחד בלבד."""
    key = _key_for_rl(ev.type, ev.context)
    now = time.time()
    last, cnt = _rl_map.get(key, (0.0, 0))
    if now - last <= RATE_LIMIT_WINDOW_S:
        # מאחד: מעלים מונה, לא דוחפים לאוסף ה"חדשים"
        _rl_map[key] = (now, cnt + 1)
        return None
    else:
        # חלון חדש: מעדכנים נקודת התחלה, מונים = 1
        _rl_map[key] = (now, 1)
        return ev

def _push_recent(ev_dict: Dict[str, Any]) -> None:
    """שומר בזיכרון את N האירועים האחרונים בצורה מעגלית."""
    if len(_recent) >= RECENT_MAX:
        _recent.pop(0)
    _recent.append(ev_dict)

def emit(
    ev_type: str,
    *,
    severity: Optional[str] = None,
    message: str = "",
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    library_version: Optional[str] = None,
    payload_version: Optional[str] = None,
) -> Dict[str, Any]:
    """
    יוצר אינדיקציה חדשה.
    מחזיר dict האירוע שנכתב (או אוחד), כך שניתן יהיה לבחון אותו בבדיקות.
    """
    if severity is None:
        severity = DEFAULT_SEVERITY_BY_TYPE.get(ev_type, "info")

    context = dict(context or {})
    tags = list(tags or [])

    ev = DiagEvent(
        time_ms=_now_ms(),
        type=ev_type,
        severity=str(severity),
        message=str(message or ""),
        context=context,
        tags=tags,
        library_version=library_version,
        payload_version=payload_version,
        count=1,
    )

    with _lock:
        # Rate-limit / איחוד
        candidate = _apply_rate_limit(ev)
        if candidate is None:
            # מאוחד בלבד — לא מציגים שוב ב-"Recent", אבל כן כותבים ללוג כדי לשמר עקבות?
            # כאן נשמור מינימליזם: לא כותבים כל דופק מאוחד כדי למנוע הצפה בקובץ.
            # אם תרצה – אפשר לשנות למדיניות "כתיבת סיכום" בסוף חלון.
            return {"merged": True, "event_type": ev_type}

        ev_dict = asdict(candidate)
        # כתיבה ללוג (לא עוצרים במקרה כשל)
        log_writer.write_event_line(ev_dict)
        # שמירה לאחרונים
        _push_recent(ev_dict)
        return ev_dict

def get_recent(limit: int = 100, *, severity: Optional[str] = None, ev_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    מחזיר עד limit האירועים האחרונים, עם סינון אופציונלי לפי חומרה/סוג.
    """
    with _lock:
        data = list(_recent)
    if severity:
        data = [d for d in data if d.get("severity") == severity]
    if ev_type:
        data = [d for d in data if d.get("type") == ev_type]
    return data[-limit:]
