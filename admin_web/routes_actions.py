# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# admin_web/routes_actions.py — Action Bus + Video State (מותאם ל-VideoStreamer הקיים)
# -----------------------------------------------------------------------------
from __future__ import annotations
import time, threading
from typing import Dict, Any, Callable, Optional
from flask import Blueprint, request, jsonify

# גישה לסטרימר הקיים שלך
from app.ui.video import get_streamer

# ----------------------------
# Action Bus: /api/action
# ----------------------------
actions_bp = Blueprint("actions", __name__)
_ACTIONS: Dict[str, Callable[[dict], dict]] = {}

def register_action(name: str):
    def deco(func: Callable[[dict], dict]):
        _ACTIONS[name] = func
        return func
    return deco

@actions_bp.route("/api/action", methods=["POST"])
def action_dispatch():
    data = request.get_json(silent=True) or {}
    action = data.get("action"); payload = data.get("payload") or {}
    if not action or action not in _ACTIONS:
        return jsonify({"ok": False, "error": f"unknown action: {action}"}), 400
    try:
        out = _ACTIONS[action](payload)
        return jsonify({"ok": True, "data": out or {}})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ----------------------------
# Video State: /api/video/state
# ----------------------------
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
    "effective": {        # מה באמת קורה בסטרים
        "fps": 0.0,
        "size": [0, 0],
    },
    "version": 1,
    "applied_at": time.time(),
}

def _bump_state(update: Dict[str, Any]) -> Dict[str, Any]:
    with _VIDEO_LOCK:
        # merge עדין
        for k, v in update.items():
            if k in ("intent", "effective") and isinstance(v, dict):
                _STATE[k].update(v)
            else:
                _STATE[k] = v
        _STATE["version"] += 1
        _STATE["applied_at"] = time.time()
        return dict(_STATE)

def get_video_state() -> Dict[str, Any]:
    with _VIDEO_LOCK:
        return dict(_STATE)

def update_effective_metrics(width: int, height: int, fps: float) -> None:
    _bump_state({"effective": {"size": [int(width), int(height)], "fps": float(fps)}})

@state_bp.route("/api/video/state", methods=["GET"])
def video_state_endpoint():
    with _VIDEO_LOCK:
        return jsonify({"ok": True, "state": _STATE})

# ----------------------------
# פעולות מותאמות ל-VideoStreamer
# ----------------------------

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
            s.set_target_fps(int(intent["target_fps"]))
        except Exception:
            pass
    # decimation (דילוג פריימים)
    if "decimation" in intent:
        try:
            s.set_decimation(int(intent["decimation"]))
        except Exception:
            pass

    # החזרה של מצב עדכני (intent + effective כפי שיש כרגע)
    eff_size = s.last_frame_size() or (0, 0)
    eff_fps  = float(s.last_fps() or 0.0)
    return {
        "intent": intent,
        "effective": {"size": [int(eff_size[0]), int(eff_size[1])], "fps": eff_fps}
    }

@register_action("video.set_profile")
def action_video_set_profile(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip() or "Balanced"
    # פרופילים בסיסיים (תואמים ליכולות שלך)
    PROFILES = {
        "Eco":      {"jpeg_q": 55, "encode_fps": 12, "target_fps": 15, "decimation": 2},
        "Balanced": {"jpeg_q": 70, "encode_fps": 15, "target_fps": 20, "decimation": 1},
        "Quality":  {"jpeg_q": 85, "encode_fps": 20, "target_fps": 24, "decimation": 1},
    }
    if name not in PROFILES:
        raise ValueError(f"unknown profile: {name}")
    intent = dict(PROFILES[name]); intent["profile"] = name
    applied = _apply_streamer_intents(intent)
    st = _bump_state({"intent": intent, "effective": applied.get("effective", {})})
    return {"state": st}

@register_action("video.set_params")
def action_video_set_params(payload: dict) -> dict:
    # params מותרים ידניים:
    intent = {}
    if "jpeg_q" in payload:     intent["jpeg_q"] = max(40, min(int(payload["jpeg_q"]), 95))
    if "encode_fps" in payload: intent["encode_fps"] = max(0, int(payload["encode_fps"]))  # 0 = ללא הגבלה (לא מומלץ)
    if "target_fps" in payload: intent["target_fps"] = max(1, int(payload["target_fps"]))
    if "decimation" in payload: intent["decimation"] = max(1, int(payload["decimation"]))
    if not intent:
        return {"warning": "no_params_given"}

    applied = _apply_streamer_intents(intent)
    st = _bump_state({"intent": intent, "effective": applied.get("effective", {})})
    return {"state": st}

@register_action("ping")
def action_ping(_payload: dict) -> dict:
    return {"pong": True, "ts": time.time()}
