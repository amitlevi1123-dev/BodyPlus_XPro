# -*- coding: utf-8 -*-
"""
admin_web/routes_exercise.py
----------------------------
ראוטים רזים ל-Exercise API, משתמשים בלוגיקה שב-admin_web/exercise_analyzer.py.

Endpoints:
- GET    /api/exercise/settings
- POST   /api/exercise/simulate
- POST   /api/exercise/score
- POST   /api/exercise/detect
- GET    /api/exercise/last
- GET    /api/exercise/diag/stream
- GET    /api/exercise/diag          ← חדש (Snapshot בשביל הכפתור)
- GET    /api/connection/status
- GET    /api/exercise/last/json
"""

from __future__ import annotations
from typing import Optional, Dict, Any
from flask import Blueprint, jsonify, request, Response, stream_with_context
import json, time

from admin_web.exercise_analyzer import (
    settings_dump,
    simulate_exercise,
    analyze_exercise,
    detect_once,
    get_last_report,
    configure_engine_root,
)

bp_exercise = Blueprint("exercise", __name__, url_prefix="/api/exercise")

# ─────────────────────────────────────────────────────────────────────────────
# 🔹 תרגילי ניתוח וניקוד
# ─────────────────────────────────────────────────────────────────────────────

@bp_exercise.get("/settings")
def exercise_settings():
    """חשיפת הגדרות מנוע התרגילים (אם זמין)."""
    out = settings_dump()
    code = 200 if out.get("ok") else (503 if out.get("error") == "engine_unavailable" else 500)
    return jsonify(out), code


@bp_exercise.post("/simulate")
def exercise_simulate():
    """
    סימולציית סטים/חזרות לצרכי UI.
    Body JSON:
      { sets:int=1, reps:int=6, mean_score:float=0.75, std:float=0.1,
        mode:str?, noise:float?, seed:int? }
    """
    j = request.get_json(silent=True) or {}
    try:
        sets = int(j.get("sets", 1))
        reps = int(j.get("reps", 6))
        mean = float(j.get("mean_score", 0.75))
        std  = float(j.get("std", 0.10))
    except Exception:
        return jsonify(ok=False, error="bad_params"), 400

    out = simulate_exercise(
        sets=sets,
        reps=reps,
        mean_score=mean,
        std=std,
        mode=j.get("mode"),
        noise=j.get("noise"),
        seed=j.get("seed", 42),
    )
    return jsonify(out), 200


@bp_exercise.post("/score")
def exercise_score():
    """
    ניקוד דו"ח יחיד מתוך metrics (ללא מנוע runtime).
    Body JSON:
      { metrics: { ... }, exercise: { id?: str } }
    """
    j = request.get_json(silent=True) or {}
    metrics = j.get("metrics")
    if not isinstance(metrics, dict):
        return jsonify(ok=False, error="no_metrics"), 400

    result = analyze_exercise({"metrics": metrics, "exercise": j.get("exercise") or {}})
    return jsonify(result), 200


@bp_exercise.post("/detect")
def exercise_detect():
    """
    זיהוי/ניתוח דרך מנוע ה-runtime (אם זמין).
    Body JSON:
      { metrics: { ... }, exercise_id?: str }
    """
    j = request.get_json(silent=True) or {}
    metrics_raw = j.get("metrics")
    if not isinstance(metrics_raw, dict):
        return jsonify(ok=False, error="missing_metrics_object"), 400

    # שמירה למסד (אם זמינה) כ-callback אופציונלי
    persist_cb = None
    try:
        from db.persist import AVAILABLE as DB_ON, persist_report  # type: ignore
        if DB_ON:
            persist_cb = persist_report
    except Exception:
        persist_cb = None

    out = detect_once(
        raw_metrics=metrics_raw,
        exercise_id=j.get("exercise_id"),
        persist_cb=persist_cb,
    )

    if out.get("ok"):
        return jsonify(out), 200

    err = (out.get("error") or "").lower()
    if "engine_unavailable" in err:
        return jsonify(out), 503
    if "library_load_failed" in err:
        return jsonify(out), 500
    if "runtime_failed" in err:
        return jsonify(out), 500
    return jsonify(out), 500


@bp_exercise.get("/last")
def exercise_last():
    """החזרת הדו״ח האחרון שנשמר במודול."""
    rep = get_last_report()
    return jsonify(ok=bool(rep), report=rep), 200


# ─────────────────────────────────────────────────────────────────────────────
# 🔵 דיאגנוסטיקה חיה + Snapshot + JSON מלא
# ─────────────────────────────────────────────────────────────────────────────

@bp_exercise.get("/diag/stream")
def api_exercise_diag_stream():
    """SSE (Server Sent Events) להזרים דיאגנוסטיקה חיה – פעם בשנייה"""
    from admin_web.state import get_payload as get_shared_payload
    try:
        ping_ms = int(request.args.get("ping_ms") or 15000)
        ping_ms = max(1000, ping_ms)
    except Exception:
        ping_ms = 15000

    def snapshot():
        snap = {}
        try:
            snap = get_shared_payload() or {}
        except Exception:
            pass
        if not snap:
            rep = get_last_report() or {}
            snap = dict(rep)
        metrics = snap.get("metrics") or {}
        keys = list(metrics.keys())[:40] if isinstance(metrics, dict) else []
        return {
            "ts": int(time.time()),
            "view_mode": snap.get("view_mode"),
            "meta": snap.get("meta", {}),
            "metrics_keys": keys,
        }

    def gen():
        last_ping = time.time()
        while True:
            yield f"data: {json.dumps(snapshot(), ensure_ascii=False)}\n\n"
            time.sleep(1.0)
            if (time.time() - last_ping) * 1000.0 >= ping_ms:
                yield ":ping\n\n"
                last_ping = time.time()

    return Response(stream_with_context(gen()), mimetype="text/event-stream")


@bp_exercise.get("/diag")
def api_exercise_diag_snapshot():
    """Snapshot סינכרוני (כפתור 'Snapshot' ב־UI)"""
    try:
        from admin_web.state import get_payload as get_shared_payload
        snap = get_shared_payload() or get_last_report() or {}
        metrics = snap.get("metrics") or {}
        keys = list(metrics.keys())[:40] if isinstance(metrics, dict) else []
        return jsonify({
            "ts": int(time.time()),
            "view_mode": snap.get("view_mode"),
            "meta": snap.get("meta", {}),
            "metrics_keys": keys,
            "has_report": bool(get_last_report()),
        }), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@bp_exercise.get("/last/json")
def open_last_json():
    """פותח את הדוח האחרון כ-JSON מלא (להצגה או הורדה)"""
    try:
        rep = get_last_report() or {}
        if not rep:
            return jsonify({"ok": False, "error": "no_last_report"}), 404
        return Response(json.dumps(rep, indent=2, ensure_ascii=False), mimetype="application/json")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@bp_exercise.get("/connection/status")
def connection_status():
    """בודק שהכול מחובר כמו שצריך (DB, מצלמה, payload)"""
    try:
        from admin_web.server import _import_get_streamer, DB_PERSIST_AVAILABLE, APP_VERSION, PAYLOAD_VERSION
        from admin_web.state import get_payload as get_shared_payload

        payload_ok = bool(get_shared_payload() or get_last_report())
        gs = _import_get_streamer()()
        video_ok = bool(getattr(gs, "is_open", lambda: False)()) if gs else False
        db_ok = DB_PERSIST_AVAILABLE
        ok = all([payload_ok, video_ok, db_ok])
        return jsonify({
            "ok": ok,
            "payload_ok": payload_ok,
            "video_ok": video_ok,
            "db_ok": db_ok,
            "app_version": APP_VERSION,
            "payload_version": PAYLOAD_VERSION,
        }), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
