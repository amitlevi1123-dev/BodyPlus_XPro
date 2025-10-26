# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# admin_web/routes_actions.py — Action Bus + Video State (מותאם ל-VideoStreamer)
# -----------------------------------------------------------------------------
from __future__ import annotations

import time
import threading
from typing import Dict, Any, Callable, Optional, Tuple
from flask import Blueprint, request, jsonify

# --------- גישה לסטרימר: נסה תחילה את app.ui.video, ואם לא — מה-BP של הווידאו ---------
def _import_get_streamer() -> Callable[[], Any]:
    try:
        from app.ui.video import get_streamer as f  # type: ignore
        return f
    except Exception:
        pass
    try:
        from admin_web.routes_video import get_streamer as f  # type: ignore
        return f
    except Exception:
        pass
    def _noop():
        raise RuntimeError("Video streamer is not available")
    return _noop

get_streamer = _import_get_streamer()

# -----------------------------------------------------------------------------
#                               Action Bus (/api/action)
# -----------------------------------------------------------------------------
actions_bp = Blueprint("actions", __name__)
_ACTIONS: Dict[str, Callable[[dict], dict]] = {}
_ACTION_DOCS: Dict[str, str] = {}  # תיאור קצר לכל פעולה (לדיבוג / עזרה)

def register_action(name: str, desc: str = ""):
    """דקורטור לרישום פעולה לאוטובוס הפעולות."""
    def deco(func: Callable[[dict], dict]):
        _ACTIONS[name] = func
        if desc:
            _ACTION_DOCS[name] = desc
        return func
    return deco

@actions_bp.route("/api/action", methods=["POST", "OPTIONS"])
def action_dispatch():
    """
    POST JSON:
      { "action": "<name>", "payload": {...} }
    """
    if request.method == "OPTIONS":
        # CORS preflight — התשובה בפועל תיסגר ע"י after_request של השרת
        return ("", 204)

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "").strip()
    payload = data.get("payload") or {}

    if not action:
        return jsonify({"ok": False, "error": "missing_action"}), 400
    if action not in _ACTIONS:
        return jsonify({"ok": False, "error": f"unknown_action:{action}"}), 400

    try:
        out = _ACTIONS[action](payload if isinstance(payload, dict) else {})
        return jsonify({"ok": True, "data": out or {}, "action": action})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "action": action}), 500

@actions_bp.route("/api/action/list", methods=["GET"])
def action_list():
    """נוח לדיבוג: מחזיר את שמות האקשנים הרשומים ותיאור קצר."""
    items = [{"name": k, "desc": _ACTION_DOCS.get(k, "")} for k in sorted(_ACTIONS.keys())]
    return jsonify({"ok": True, "actions": items, "total": len(items)})

# -----------------------------------------------------------------------------
#                         Video State (/api/video/state)
# -----------------------------------------------------------------------------
state_bp = Blueprint("video_state", __name__)
_VIDEO_LOCK = threading.Lock()

# נשמור גם "כוונות" (params שרוצים להחיל) וגם "מצב בפועל" (effective)
_STATE: Dict[str, Any] = {
    "intent": {           # מה המשתמש ביקש
        "jpeg_q": 70,
        "encode_fps": 15,
        "target_fps": 30,
        "decimation": 1,
        "profile": "Balanced",
    },
    "effective": {        # מה באמת קורה בסטרים (נמדד מה-Streamer)
        "fps": 0.0,
        "size": [0, 0],
        "source": "unknown",
    },
    "version": 1,
    "applied_at": time.time(),
}

def _bump_state(update: Dict[str, Any]) -> Dict[str, Any]:
    """מאחד עדכונים לתוך ה-STATE באופן בטוח לשרשורים."""
    with _VIDEO_LOCK:
        for k, v in update.items():
            if k in ("intent", "effective") and isinstance(v, dict):
                _STATE[k].update(v)
            else:
                _STATE[k] = v
        _STATE["version"] = int(_STATE.get("version", 0)) + 1
        _STATE["applied_at"] = time.time()
        return dict(_STATE)

def get_video_state() -> Dict[str, Any]:
    with _VIDEO_LOCK:
        return dict(_STATE)

def _snapshot_effective_from_streamer() -> Dict[str, Any]:
    """קורא מהסטרימר את המצב האחרון ויוצר מבנה effective סטנדרטי."""
    s = get_streamer()
    try:
        size = s.last_frame_size() if callable(getattr(s, "last_frame_size", None)) else getattr(s, "last_frame_size", (0, 0))
    except Exception:
        size = (0, 0)
    try:
        fps = s.last_fps() if callable(getattr(s, "last_fps", None)) else getattr(s, "last_fps", 0.0)
    except Exception:
        fps = 0.0
    try:
        source = s.source_name() if callable(getattr(s, "source_name", None)) else getattr(s, "source_name", "camera")
    except Exception:
        source = "camera"

    w, h = (int(size[0]), int(size[1])) if isinstance(size, (tuple, list)) and len(size) >= 2 else (0, 0)
    return {"size": [w, h], "fps": float(fps or 0.0), "source": str(source or "unknown")}

def update_effective_metrics(width: int, height: int, fps: float) -> None:
    """אפשר לזמן מבחוץ (למשל מהסטרימר) כדי לעדכן FPS וגודל."""
    _bump_state({"effective": {"size": [int(width), int(height)], "fps": float(fps)}})

@state_bp.route("/api/video/state", methods=["GET"])
def video_state_endpoint():
    """מחזיר את מצב הווידאו הנוכחי (intent + effective)."""
    with _VIDEO_LOCK:
        return jsonify({"ok": True, "state": _STATE})

@state_bp.route("/api/video/state/refresh", methods=["POST"])
def video_state_refresh():
    """
    מאלץ רענון מידי של מדדי effective מהסטרימר, ומחזיר את ה-state המעודכן.
    עוזר אם הלקוח רוצה pull תקופתי.
    """
    eff = _snapshot_effective_from_streamer()
    st = _bump_state({"effective": eff})
    return jsonify({"ok": True, "state": st})

# -----------------------------------------------------------------------------
#                     פעולות מותאמות ל-VideoStreamer (Action Bus)
# -----------------------------------------------------------------------------
def _apply_streamer_intents(intent: Dict[str, Any]) -> Dict[str, Any]:
    """
    מנסה להחיל כוונות על ה-VideoStreamer שלך (שדות קיימים במחלקה).
    לא שובר אם שדה לא קיים — מתעלם בשקט.
    """
    s = get_streamer()
    # jpeg_quality
    if "jpeg_q" in intent:
        try:
            s.jpeg_quality = int(intent["jpeg_q"])
        except Exception:
            pass
    # encode_fps (קצב יציאה ל-MJPEG)
    if "encode_fps" in intent:
        try:
            v = int(intent["encode_fps"])
            if v >= 0:
                s.encode_fps = v
        except Exception:
            pass
    # target_fps (קצב קריאה מהמצלמה)
    if "target_fps" in intent:
        try:
            if callable(getattr(s, "set_target_fps", None)):
                s.set_target_fps(int(intent["target_fps"]))
            else:
                s.target_fps = int(intent["target_fps"])
        except Exception:
            pass
    # decimation (דילוג פריימים)
    if "decimation" in intent:
        try:
            if callable(getattr(s, "set_decimation", None)):
                s.set_decimation(int(intent["decimation"]))
            else:
                s.decimation = int(intent["decimation"])
        except Exception:
            pass

    # החזרה של מצב עדכני (intent + effective כפי שיש כרגע)
    eff = _snapshot_effective_from_streamer()
    return {"intent": intent, "effective": eff}

# ---- פרופילים מוכנים ----
_PROFILES: Dict[str, Dict[str, Any]] = {
    "Eco":      {"jpeg_q": 55, "encode_fps": 12, "target_fps": 15, "decimation": 2},
    "Balanced": {"jpeg_q": 70, "encode_fps": 15, "target_fps": 20, "decimation": 1},
    "Quality":  {"jpeg_q": 85, "encode_fps": 20, "target_fps": 24, "decimation": 1},
}

def _validate_profile_name(name: str) -> str:
    n = (name or "").strip() or "Balanced"
    if n not in _PROFILES:
        raise ValueError(f"unknown profile: {n}")
    return n

@register_action("video.set_profile", desc="החלפת פרופיל קידוד/קצב לסטרים")
def action_video_set_profile(payload: dict) -> dict:
    name = _validate_profile_name(str(payload.get("name", "")))
    intent = dict(_PROFILES[name]); intent["profile"] = name
    applied = _apply_streamer_intents(intent)
    st = _bump_state({"intent": intent, "effective": applied.get("effective", {})})
    return {"state": st}

@register_action("video.set_params", desc="קביעת פרמטרים ידניים (jpeg_q / encode_fps / target_fps / decimation)")
def action_video_set_params(payload: dict) -> dict:
    # params מותרים ידניים:
    intent: Dict[str, Any] = {}
    if "jpeg_q" in payload:     intent["jpeg_q"] = max(40, min(int(payload["jpeg_q"]), 95))
    if "encode_fps" in payload: intent["encode_fps"] = max(0, int(payload["encode_fps"]))  # 0 = ללא הגבלה (לא מומלץ)
    if "target_fps" in payload: intent["target_fps"] = max(1, int(payload["target_fps"]))
    if "decimation" in payload: intent["decimation"] = max(1, int(payload["decimation"]))
    if "profile" in payload:    intent["profile"] = str(payload["profile"]).strip() or "Custom"

    if not intent:
        return {"warning": "no_params_given"}

    applied = _apply_streamer_intents(intent)
    st = _bump_state({"intent": intent, "effective": applied.get("effective", {})})
    return {"state": st}

@register_action("video.refresh_effective", desc="רענון מיידי של effective מהסטרימר")
def action_video_refresh_effective(_payload: dict) -> dict:
    eff = _snapshot_effective_from_streamer()
    st = _bump_state({"effective": eff})
    return {"state": st}

@register_action("ping", desc="בדיקת חיים פשוטה")
def action_ping(_payload: dict) -> dict:
    return {"pong": True, "ts": time.time()}
