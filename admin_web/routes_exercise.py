# -*- coding: utf-8 -*-
"""
admin_web/routes_exercise.py
----------------------------
ראוטים רזים ל-Exercise API, מבוססי הלוגיקה שב-admin_web/exercise_analyzer.py.

Endpoints:
- GET    /api/exercise/settings
- POST   /api/exercise/simulate
- POST   /api/exercise/score        ← כרגע ממופה ל-detect (עד שיתווסף analyze_offline)
- POST   /api/exercise/detect
- GET    /api/exercise/last
- GET    /api/exercise/diag/stream
- GET    /api/exercise/diag
- GET    /api/exercise/connection/status
- GET    /api/exercise/last/json
"""

from __future__ import annotations
from typing import Optional, Dict, Any
from flask import Blueprint, jsonify, request, Response, stream_with_context
import json, time

# ─────────────────────────────────────────────────────────────────────────────
# ייבוא פונקציות מהמנתח
# ─────────────────────────────────────────────────────────────────────────────
from admin_web.exercise_analyzer import (
    detect_once,
    simulate_full_reports,
    get_last_report,
    get_engine_library,   # לשימוש פנימי ב-settings
    EXR_SETTINGS,         # יתכן None אם המנוע לא זמין
)

bp_exercise = Blueprint("exercise", __name__, url_prefix="/api/exercise")


# ─────────────────────────────────────────────────────────────────────────────
# 🧩 עזר: settings_dump (ללא תלות חיצונית)
# ─────────────────────────────────────────────────────────────────────────────
def settings_dump() -> Dict[str, Any]:
    """
    מחזיר סטטוס מנוע ופרטי ספרייה (אם נטענה) בצורה ידידותית ל-UI.
    """
    out: Dict[str, Any] = {"ok": True, "engine": {}, "library": {}}
    try:
        engine_ok = EXR_SETTINGS is not None
        out["engine"] = {
            "available": engine_ok,
            "settings_present": bool(EXR_SETTINGS is not None),
        }

        lib = None
        lib_root = None
        if engine_ok:
            try:
                lib = get_engine_library()
                lib_root = getattr(lib, "root_dir", None) or getattr(lib, "root", None)
            except Exception as e:
                out["engine"]["available"] = False
                out["engine"]["error"] = f"library_load_failed: {e}"

        if lib:
            # ננסה לסכם מידע בסיסי—שדות אופציונליים בלודר שלך
            families = sorted(list(getattr(lib, "families", {}).keys())) if getattr(lib, "families", None) else []
            exercises = sorted(list(getattr(lib, "exercises", {}).keys())) if getattr(lib, "exercises", None) else []
            out["library"] = {
                "loaded": True,
                "root": str(lib_root) if lib_root else None,
                "families_count": len(families),
                "exercises_count": len(exercises),
            }
        else:
            out["library"] = {"loaded": False}

        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 🔹 תרגילי ניתוח וניקוד
# ─────────────────────────────────────────────────────────────────────────────
@bp_exercise.get("/settings")
def exercise_settings():
    """חשיפת הגדרות מנוע התרגילים ומצב טעינת הספרייה."""
    out = settings_dump()
    code = 200 if out.get("ok") else 500
    if out.get("engine", {}).get("available") is False:
        code = 503
    return jsonify(out), code


@bp_exercise.post("/simulate")
def exercise_simulate():
    """
    סימולציית סטים/חזרות לצרכי UI (ללא מנוע).
    Body JSON:
      {
        "sets": int = 1,
        "reps": int = 6,
        "mode": "mixed" | "easy" | "hard",
        "noise": float = 0.2
      }
    """
    j = request.get_json(silent=True) or {}
    try:
        sets = int(j.get("sets", 1))
        reps = int(j.get("reps", 6))
        mode = j.get("mode", "mixed")
        noise = float(j.get("noise", 0.2))
    except Exception:
        return jsonify(ok=False, error="bad_params"), 400

    out = simulate_full_reports(sets=sets, reps=reps, mode=mode, noise=noise)
    return jsonify(out), 200


@bp_exercise.post("/score")
def exercise_score():
    """
    ניקוד דו"ח מתוך metrics.
    כרגע: ממפה ל-detect_once (כלומר משתמש במנוע runtime אם זמין),
    כדי לשמור עקביות עד שתתווסף פונקציה analyze_offline ייעודית.
    Body JSON:
      { "metrics": { ... }, "exercise_id": str? }
    """
    j = request.get_json(silent=True) or {}
    metrics = j.get("metrics")
    if not isinstance(metrics, dict):
        return jsonify(ok=False, error="no_metrics"), 400

    out = detect_once(raw_metrics=metrics, exercise_id=j.get("exercise_id"))
    if out.get("ok"):
        return jsonify(out), 200

    err = (out.get("error") or "").lower()
    if "engine_unavailable" in err:
        return jsonify(out), 503
    if "library_load_failed" in err or "runtime_failed" in err:
        return jsonify(out), 500
    return jsonify(out), 500


@bp_exercise.post("/detect")
def exercise_detect():
    """
    זיהוי/ניתוח דרך מנוע ה-runtime (אם זמין).
    Body JSON:
      { "metrics": { ... }, "exercise_id": str? }
    """
    j = request.get_json(silent=True) or {}
    metrics_raw = j.get("metrics")
    if not isinstance(metrics_raw, dict):
        return jsonify(ok=False, error="missing_metrics_object"), 400

    out = detect_once(
        raw_metrics=metrics_raw,
        exercise_id=j.get("exercise_id"),
    )

    if out.get("ok"):
        return jsonify(out), 200

    err = (out.get("error") or "").lower()
    if "engine_unavailable" in err:
        return jsonify(out), 503
    if "library_load_failed" in err or "runtime_failed" in err:
        return jsonify(out), 500
    return jsonify(out), 500


@bp_exercise.get("/last")
def exercise_last():
    """החזרת הדו״ח האחרון שנשמר במודול (אם נשמר)."""
    rep = get_last_report()
    return jsonify(ok=bool(rep), report=rep), 200


# ─────────────────────────────────────────────────────────────────────────────
# 🔵 דיאגנוסטיקה חיה + Snapshot + JSON מלא
# ─────────────────────────────────────────────────────────────────────────────
@bp_exercise.get("/diag/stream")
def api_exercise_diag_stream():
    """SSE (Server Sent Events) להזרים דיאגנוסטיקה חיה – פעם בשנייה."""
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
    """Snapshot סינכרוני (כפתור 'Snapshot' ב־UI)."""
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
    """פותח את הדוח האחרון כ-JSON מלא (להצגה/הורדה)."""
    try:
        rep = get_last_report() or {}
        if not rep:
            return jsonify({"ok": False, "error": "no_last_report"}), 404
        return Response(json.dumps(rep, indent=2, ensure_ascii=False), mimetype="application/json")
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500


@bp_exercise.get("/connection/status")
def connection_status():
    """
    בדיקת חיבוריות מהירה: payload/video/db + גרסאות.
    דורש:
      - admin_web.server: APP_VERSION, PAYLOAD_VERSION, _import_get_streamer()
      - admin_web.state.get_payload()  (אופציונלי)
    """
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
