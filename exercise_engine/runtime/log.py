# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# exercise_engine/runtime/log.py
# מעטפת לוגים ואינדיקציות:
#  - emit(event, severity, message, **context) → רושם לזיכרון ול־JSONL
#  - tail(limit=50) → מחזיר את סוף הרשומות (מהזיכרון) בפורמט List[dict]
#
# קובץ לוג: exercise_engine/runtime/logs/diagnostics-YYYY-MM-DD.jsonl
# שמיש גם אם אין הרשאות כתיבה (נופל חזרה לזיכרון בלבד).
# -----------------------------------------------------------------------------

from __future__ import annotations
import os
import json
import datetime as _dt
from collections import deque
from threading import RLock
from typing import Dict, Any, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# הגדרות בסיס
# ─────────────────────────────────────────────────────────────────────────────

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_DIR = os.path.join(_BASE_DIR, "logs")
_MAX_INMEM = 2000  # כמה רשומות נשמור בזיכרון
_BUF: deque = deque(maxlen=_MAX_INMEM)
_LOCK = RLock()

def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _log_path_for_today() -> str:
    date = _dt.datetime.now().strftime("%Y-%m-%d")
    return os.path.join(_LOG_DIR, f"diagnostics-{date}.jsonl")

# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────

def emit(event: str, severity: str, message: str, **context: Any) -> None:
    """
    רישום אינדיקציה / לוג:
    - event: שם האירוע (str)
    - severity: 'info' | 'warn' | 'error' | ...
    - message: מחרוזת תיאור
    - context: key=value חופשי (serializable)
    """
    rec = {
        "ts": _dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "event": str(event),
        "severity": str(severity).lower(),
        "message": str(message),
        "context": context or {},
    }

    with _LOCK:
        # זיכרון
        _BUF.append(rec)

        # דיסק (best-effort)
        try:
            _ensure_dir(_LOG_DIR)
            p = _log_path_for_today()
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            # לא נכשיל את היישום בגלל כשל כתיבה
            pass

def tail(limit: int = 50) -> List[Dict[str, Any]]:
    """
    מחזיר את N הרשומות האחרונות מהזיכרון (לא קורא מהדיסק).
    """
    if limit <= 0:
        return []
    with _LOCK:
        n = min(limit, len(_BUF))
        # deque לא תומך slicing ישיר, נעשה המרה לרשימה רק לקטע הנדרש
        return list(_BUF)[-n:]

# אופציונלי: ניקוי לוגים ישנים (לא חובה לשימוש)
def _cleanup_old_logs(retention_days: int = 14) -> None:
    """
    מוחק קובצי JSONL ישנים מהתיקייה לפי מספר ימים.
    לא נקרא אוטומטית; אפשר מזמן לזמן בבדיקות/סטארט-אפ.
    """
    try:
        _ensure_dir(_LOG_DIR)
        now = _dt.datetime.now()
        for name in os.listdir(_LOG_DIR):
            if not name.startswith("diagnostics-") or not name.endswith(".jsonl"):
                continue
            path = os.path.join(_LOG_DIR, name)
            try:
                mtime = _dt.datetime.fromtimestamp(os.path.getmtime(path))
                if (now - mtime).days > retention_days:
                    os.remove(path)
            except Exception:
                pass
    except Exception:
        pass
