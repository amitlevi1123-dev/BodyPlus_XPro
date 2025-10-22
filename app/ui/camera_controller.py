# -*- coding: utf-8 -*-
"""
app/ui/camera_controller.py — בקר הגדרות מצלמה בזמן ריצה
--------------------------------------------------------
תיאור (I/O):
- שומר מצביע ל-VideoCapture קיים (אם יש), ומאפשר להחליף FPS/רזולוציה.
- אם שינוי "חי" נכשל, מבצע reopen עם הפרמטרים החדשים.
- שימוש:
    from app.ui.camera_controller import register_cap, apply_settings, get_settings

    # במקום שבו אתה פותח מצלמה:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    register_cap(cap, source={"type": "camera", "index": index}, width=1280, height=720, fps=30)

    # API יקרא:
    apply_settings(fps=15, width=1280, height=720)
"""
from __future__ import annotations
import threading
from typing import Optional, Dict, Any, Tuple

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None  # type: ignore

_LOCK = threading.RLock()
_CAP = None  # type: ignore
_SOURCE: Dict[str, Any] = {"type": "camera", "index": 0}
_SETTINGS: Dict[str, Any] = {"fps": 30, "width": 1280, "height": 720}

def register_cap(cap, source: Optional[Dict[str, Any]] = None,
                 width: Optional[int] = None, height: Optional[int] = None,
                 fps: Optional[int] = None) -> None:
    """רישום ה-Capture הפעיל + מקור. קריאה מהמקום שבו פותחים מצלמה."""
    global _CAP, _SOURCE, _SETTINGS
    with _LOCK:
        _CAP = cap
        if source:
            _SOURCE = dict(source)
        if width:  _SETTINGS["width"]  = int(width)
        if height: _SETTINGS["height"] = int(height)
        if fps:    _SETTINGS["fps"]    = int(fps)

def get_settings() -> Dict[str, Any]:
    """החזרה עבור ה-API (מצב נוכחי)."""
    with _LOCK:
        return dict(_SETTINGS)

def _try_set_live(cap, fps: int, width: int, height: int) -> bool:
    """ניסיון לשנות פרמטרים על cap פתוח. לא כל מצלמה מכבדת."""
    if cv2 is None or cap is None:
        return False
    ok = True
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    except Exception:
        pass
    try:
        ok &= bool(cap.set(cv2.CAP_PROP_FPS, float(fps)))
    except Exception:
        ok = False
    try:
        ok &= bool(cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(width)))
        ok &= bool(cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height)))
    except Exception:
        ok = False
    return ok

def _open_new_camera(index: int, fps: int, width: int, height: int):
    """פותח מצלמה עם פרמטרים. מחזיר cap חדש או None."""
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    except Exception:
        pass
    try: cap.set(cv2.CAP_PROP_FPS, float(fps))
    except Exception: pass
    try:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
    except Exception:
        pass
    return cap if cap.isOpened() else None

def apply_settings(fps: int, width: int, height: int) -> Tuple[bool, str]:
    """
    מחיל הגדרות חדשות. אם לא מצליח "חי", מנסה reopen.
    מחזיר (success, message).
    """
    global _CAP, _SETTINGS, _SOURCE
    with _LOCK:
        _SETTINGS.update({"fps": int(fps), "width": int(width), "height": int(height)})

        if cv2 is None:
            return False, "cv2 לא זמין — נשמרו הגדרות בלבד."

        # אם אין cap — רק נשמור הגדרות
        if _CAP is None:
            return True, "נשמר. ישום בפעם הבאה שהמצלמה תיפתח."

        # נסיון שינוי חי
        if _try_set_live(_CAP, fps, width, height):
            return True, "עודכן על מצלמה פעילה."

        # reopen
        try:
            try:
                _CAP.release()
            except Exception:
                pass
            index = int(_SOURCE.get("index", 0))
            new_cap = _open_new_camera(index, fps, width, height)
            if new_cap is None:
                _CAP = None
                return False, "נכשל reopen — בדוק שהמצלמה פנויה."
            _CAP = new_cap
            return True, "בוצע reopen עם פרמטרים חדשים."
        except Exception as e:
            return False, f"שגיאה ב-reopen: {e!r}"
