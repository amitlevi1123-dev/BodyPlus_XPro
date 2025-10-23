# =============================================================================
# 🧠 BodyPlus XPro — app/runtime/payload.py
# =============================================================================
# מטרת הקובץ:
# מנהל את ה-"Payload" של המערכת — זה האובייקט (dict) שבו נשמרים כל
# הנתונים המחושבים בזמן אמת: זוויות, מדדים, אובייקטים שזוהו, FPS וכו’.
#
# למה זה בטוח:
# לא משנה את מבנה ה-payload, רק מוסיף "עטיפה" שמגינה עליו משינויים
# במקביל (thread-safe). זאת אומרת, גם אם Thread של Flask וגם Thread של
# מצלמה ניגשים לנתונים יחד — אין סיכון לשגיאת race.
#
# שימוש:
# במקום להחזיק self._payload ו-self._pl_lock בתוך ה-App,
# משתמשים במחלקה PayloadManager:
#
#     self.payload_mgr = PayloadManager()
#     self.payload_mgr.set({...})
#     data = self.payload_mgr.get()
#
# שתי הפונקציות הישנות _payload_set / _payload_get נשארות, כדי שכל
# שאר הקוד ימשיך לעבוד בדיוק אותו דבר.
# =============================================================================

from __future__ import annotations
import threading
from typing import Dict, Any


class PayloadManager:
    """
    מחלקה לניהול ה-Payload עם מנגנון נעילה (Lock)
    כדי למנוע התנגשויות בזמן ריבוי שרשורים.
    """

    def __init__(self) -> None:
        # נעילה אחת בלבד לכל המידע
        self._lock = threading.Lock()
        # כאן נשמר ה-Payload עצמו (dictionary)
        self._data: Dict[str, Any] = {}

    def set(self, payload: Dict[str, Any]) -> None:
        """מחליף את כל ה-Payload בבת אחת."""
        with self._lock:
            self._data = payload

    def get(self) -> Dict[str, Any]:
        """מחזיר עותק של ה-Payload הנוכחי לקריאה בלבד."""
        with self._lock:
            # dict() יוצר עותק חדש כדי שמי שקורא לא ישנה בטעות
            return dict(self._data)

    def update(self, patch: Dict[str, Any]) -> None:
        """מעדכן רק חלק מה-Keys בתוך ה-Payload."""
        with self._lock:
            self._data.update(patch)
