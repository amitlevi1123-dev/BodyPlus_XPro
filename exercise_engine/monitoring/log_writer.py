# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# הסבר קצר (עברית):
# קובץ זה אחראי על כתיבת אינדיקציות לקובץ לוג יומי בפורמט JSON Lines (JSONL).
# קלטים מרכזיים: dict אירועי אינדיקציה (time/type/severity/message/context/...).
# פלט/תוצרים: קבצי logs/diagnostics-YYYY-MM-DD.jsonl + ניקוי קבצים ישנים לפי מדיניות שמירה.
# הערות: מודול זה מופרד מ-core/Main; ניתן לשנות שמירת ימים (RETENTION_DAYS) ללא השפעה על המנוע.
# -----------------------------------------------------------------------------

from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, Iterable

# הגדרות בסיס
LOG_DIR = Path("logs")
FILE_PREFIX = "diagnostics"
RETENTION_DAYS = 14  # ניתן לשינוי לפי צורך

_lock = threading.RLock()
_current_path: Optional[Path] = None
_current_date: Optional[str] = None

def _ensure_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

def _log_path_for(date_str: str) -> Path:
    return LOG_DIR / f"{FILE_PREFIX}-{date_str}.jsonl"

def _roll_if_needed() -> None:
    """יוצר/מחליף את קובץ היום לפי תאריך (רוטציה יומית)."""
    global _current_path, _current_date
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _current_date != today or _current_path is None:
        _current_date = today
        _current_path = _log_path_for(today)
        _current_path.touch(exist_ok=True)

def _purge_old() -> None:
    """מוחק קבצי לוג ישנים לפי מדיניות שמירה."""
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    for p in LOG_DIR.glob(f"{FILE_PREFIX}-*.jsonl"):
        # ניסיון לפענח תאריך מהשם
        try:
            date_str = p.stem.split("-", 1)[1]
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except Exception:
            # אם אין תאריך חוקי בשם — לא מוחקים
            continue
        if dt < cutoff:
            try:
                p.unlink(missing_ok=True)
            except Exception:
                # לא עוצרים את הזרימה בגלל ניקוי שנכשל
                pass

def write_event_line(event: Dict[str, Any]) -> bool:
    """
    כותב אירוע JSON יחיד לשורת לוג.
    מחזיר True בהצלחה, False במקרה חריג (לא זורק שגיאה כדי לא לפגוע בזמן אמת).
    """
    try:
        with _lock:
            _ensure_dir()
            _roll_if_needed()
            if _current_path is None:
                return False
            # כתיבה כשורת JSON אחת
            with _current_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            _purge_old()
        return True
    except Exception:
        return False

def write_many(events: Iterable[Dict[str, Any]]) -> int:
    """כתיבה מרובה בבת אחת. מחזיר כמה אירועים נכתבו בפועל."""
    n = 0
    for ev in events:
        if write_event_line(ev):
            n += 1
    return n
