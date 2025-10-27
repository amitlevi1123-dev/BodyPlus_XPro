# -*- coding: utf-8 -*-
"""
admin_web/routes_system.py — 🔧 בריאות/דיאגנוסטיקה כ-Blueprint
--------------------------------------------------------------
מספק נקודות קצה לניטור מצב השרת והמערכת:

GET  /version
GET  /healthz
GET  /readyz
GET  /api/health
GET  /api/system
GET  /api/diagnostics
GET  /api/session/status
GET  /api/exercise/diag
"""

from __future__ import annotations
import os
import time
from typing import Any, Dict, Tuple

from flask import Blueprint, jsonify

bp_system = Blueprint("system", __name__)

# =========================================================
#  Utilities — lazy imports to avoid circular dependencies
# =========================================================
def _get_basic_config() -> Tuple[str, str, float]:
    """Returns (APP_VERSION, PAYLOAD_VERSION, START_TS) with safe fallbacks."""
    try:
        from server import APP_VERSION, START_TS
    except Exception:
        APP_VERSION, START_TS = os.getenv("APP_VERSION", "dev"), time.time()
    try:
        from core.payload import PAYLOAD_VERSION  # type: ignore
    except Exception:
        PAYLOAD_VERSION = "1.2.0"
    return APP_VERSION, PAYLOAD_VERSION, START_TS


def _get_snapshot():
    """system monitor snapshot (safe fallback)."""
    try:
        from core.system.monitor import get_snapshot  # type: ignore
        return get_snapshot
    except Exception:
        def _fallback() -> Dict[str, Any]:
            return {"ok": False, "error": "system_monitor_unavailable"}
        return _fallback


def _get_shared_payload_fn():
    """shared payload provider (admin_web.state) with fallback to {}."""
    try:
        from admin_web.state import get_payload  # type: ignore
        return get_payload
    except Exception:
        def _fallback() -> Dict[str, Any]:
            return {}
        return _fallback


def _get_last_payload():
    """Access to LAST_PAYLOAD + lock from server (optional)."""
    try:
        from server import LAST_PAYLOAD, LAST_PAYLOAD_LOCK  # type: ignore
        return LAST_PAYLOAD, LAST_PAYLOAD_LOCK
    except Exception:
        from threading import Lock  # safe local lock
        return None, Lock()


def _get_streamer_getter():
    """Function that returns the video streamer instance (optional)."""
    try:
        from app.ui.video import get_streamer  # type: ignore
        return get_streamer
    except Exception:
        try:
            from admin_web.routes_video import get_streamer  # type: ignore
            return get_streamer
        except Exception:
            return lambda: None


def _get_objdet_status():
    """(status, lock) from routes_objdet if available."""
    try:
        from admin_web.routes_objdet import OBJDET_STATUS, OBJDET_STATUS_LOCK  # type: ignore
        return OBJDET_STATUS, OBJDET_STATUS_LOCK
    except Exception:
        from threading import Lock
        return {"ok": False, "note": "objdet_status_unavailable"}, Lock()


# ================ Endpoints =================

@bp_system.get("/version")
def version():
    APP_VERSION, PAYLOAD_VERSION, START_TS = _get_basic_config()
    up = max(0.0, time.time() - START_TS)
    return jsonify({
        "app_version": APP_VERSION,
        "git_commit": (os.getenv("GIT_COMMIT", "")[:12] or None),
        "payload_version": PAYLOAD_VERSION,
        "uptime_sec": round(up, 1),
        "env": {"runpod": bool(os.getenv("RUNPOD_BASE"))}
    }), 200


@bp_system.get("/healthz")
def healthz():
    try:
        get_snapshot = _get_snapshot()
        snap = get_snapshot() or {}

        get_shared_payload = _get_shared_payload_fn()
        payload = get_shared_payload() or {}

        if not payload:
            LAST_PAYLOAD, LAST_PAYLOAD_LOCK = _get_last_payload()
            if isinstance(LAST_PAYLOAD, dict):
                payload = LAST_PAYLOAD or {}

        now = time.time()
        ts = float(payload.get("ts", now))
        age = max(0.0, now - ts)

        opened = running = False
        gs = _get_streamer_getter()
        if callable(gs):
            s = gs()
            try:
                opened = bool(getattr(s, "is_open", lambda: False)())
            except Exception:
                opened = bool(getattr(s, "opened", False))
            try:
                running = bool(getattr(s, "is_running", lambda: False)())
            except Exception:
                running = bool(getattr(s, "running", False))

        gpu_av = bool((snap.get("gpu") or {}).get("available", False))
        ok = (age < 3.0)
        return jsonify({
            "ok": ok,
            "payload": {"age_sec": round(age, 3), "present": bool(payload)},
            "video": {"opened": opened, "running": running},
            "gpu": {"available": gpu_av},
            "system": {"ok": bool(snap.get("ok", True))},
            "ts": int(now)
        }), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@bp_system.get("/readyz")
def readyz():
    try:
        # Templates & static existence
        try:
            from server import TPL_DIR, STATIC_DIR  # type: ignore
            t_ok = TPL_DIR.exists()
            s_ok = STATIC_DIR.exists()
        except Exception:
            # אם השרת לא מספק—נניח תקין כדי לא לחסום readiness
            t_ok = s_ok = True

        get_snapshot = _get_snapshot()
        snap_ok = True
        try:
            s = get_snapshot()
            if isinstance(s, dict) and s.get("error"):
                snap_ok = False
        except Exception:
            snap_ok = False

        gs = _get_streamer_getter()
        streamer_ok = callable(gs)

        ok = all([t_ok, s_ok, snap_ok, streamer_ok])
        code = 200 if ok else 503
        return jsonify({
            "ok": ok, "templates": t_ok, "static": s_ok,
            "system_monitor": snap_ok, "streamer_available": streamer_ok
        }), code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 503


@bp_system.get("/api/health")
def api_health():
    APP_VERSION, _, START_TS = _get_basic_config()
    return jsonify(ok=True, version=APP_VERSION, uptime_sec=round(time.time() - START_TS, 1)), 200


@bp_system.get("/api/system")
def api_system():
    try:
        get_snapshot = _get_snapshot()
        return jsonify(get_snapshot())
    except Exception as e:
        return jsonify({"ok": False, "error": f"system_api failure: {e}"}), 500


@bp_system.get("/api/diagnostics")
def api_diagnostics():
    diag: Dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
    try:
        _, PAYLOAD_VERSION, APP_START = _get_basic_config()  # APP_START unused but harmless

        get_shared_payload = _get_shared_payload_fn()
        payload = get_shared_payload() or {}

        if not payload:
            LAST_PAYLOAD, LAST_PAYLOAD_LOCK = _get_last_payload()
            if isinstance(LAST_PAYLOAD, dict):
                payload = LAST_PAYLOAD.copy()

        diag["payload_ok"] = bool(payload)
        diag["payload_version"] = payload.get("payload_version", PAYLOAD_VERSION)

        opened = running = False
        gs = _get_streamer_getter()
        if callable(gs):
            s = gs()
            try:
                opened = bool(getattr(s, "is_open", lambda: False)())
            except Exception:
                opened = bool(getattr(s, "opened", False))
            try:
                running = bool(getattr(s, "is_running", lambda: False)())
            except Exception:
                running = bool(getattr(s, "running", False))
        diag["video"] = {"opened": opened, "running": running}

        OBJDET_STATUS, OBJDET_STATUS_LOCK = _get_objdet_status()
        with OBJDET_STATUS_LOCK:
            st = dict(OBJDET_STATUS)
        diag["objdet"] = st

        APP_VERSION, _, _ = _get_basic_config()
        diag["app_version"] = APP_VERSION
        diag["ts"] = time.time()
        return jsonify(diag), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@bp_system.get("/api/session/status")
def api_session_status():
    import time as _t
    fps = 0.0
    size = (0, 0)
    source = "unknown"
    opened = False
    running = False
    try:
        gs = _get_streamer_getter()
        if callable(gs):
            s = gs()
            try:
                fps = float(getattr(s, "last_fps", lambda: 0.0)() or 0.0)
            except Exception:
                pass
            try:
                size = getattr(s, "last_frame_size", lambda: (0, 0))() or (0, 0)
            except Exception:
                pass
            try:
                source = getattr(s, "source_name", lambda: "camera")() or "camera"
            except Exception:
                pass
            try:
                opened = bool(getattr(s, "is_open", lambda: getattr(s, "opened", False))())
            except Exception:
                opened = bool(getattr(s, "opened", False))
            try:
                running = bool(getattr(s, "is_running", lambda: getattr(s, "running", False))())
            except Exception:
                running = bool(getattr(s, "running", False))
    except Exception:
        pass
    w, h = (int(size[0]), int(size[1])) if isinstance(size, (tuple, list)) and len(size) >= 2 else (0, 0)
    return jsonify({
        "opened": opened,
        "running": running,
        "fps": float(fps),
        "size": [w, h],
        "source": source,
        "ts": _t.time(),
    }), 200


@bp_system.get("/api/exercise/diag")
def api_exercise_diag_snapshot():
    import time as _t
    snap: Dict[str, Any] = {}
    try:
        get_shared_payload = _get_shared_payload_fn()
        snap = get_shared_payload() or {}
    except Exception:
        snap = {}
    if not snap:
        LAST_PAYLOAD, LAST_PAYLOAD_LOCK = _get_last_payload()
        if isinstance(LAST_PAYLOAD, dict):
            snap = dict(LAST_PAYLOAD)

    metrics = snap.get("metrics") or {}
    metrics_keys = []
    try:
        if isinstance(metrics, dict):
            metrics_keys = list(metrics.keys())
        elif isinstance(metrics, list):
            metrics_keys = [m.get("name") for m in metrics if isinstance(m, dict) and "name" in m]
    except Exception:
        metrics_keys = []

    out = {
        "ok": True,
        "ts": _t.time(),
        "view_mode": snap.get("view_mode"),
        "meta": snap.get("meta", {}),
        "metrics_keys": metrics_keys[:50],
    }
    return jsonify(out), 200
