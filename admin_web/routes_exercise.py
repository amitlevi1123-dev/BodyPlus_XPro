# -*- coding: utf-8 -*-
"""
admin_web/routes_exercise.py
----------------------------
ראוטים מלאים ל־Exercise API + תוויות UI (labels & names) מתוך YAML.

Endpoints עיקריים:
───────────────────
🧩 תרגילים:
- GET    /api/exercise/settings
- POST   /api/exercise/simulate
- POST   /api/exercise/score
- POST   /api/exercise/detect
- GET    /api/exercise/last
- GET    /api/exercise/diag/stream
- GET    /api/exercise/diag
- GET    /api/exercise/last/json
- GET    /api/exercise/connection/status

🎨 תוויות UI:
- GET    /api/exercise/ui/labels
- GET    /api/exercise/ui/metrics
- GET    /api/exercise/ui/names
- POST   /api/exercise/ui/reload
"""

from __future__ import annotations
from typing import Dict, Any
from flask import Blueprint, jsonify, request, Response, stream_with_context
import json, time, os, yaml, hashlib
from pathlib import Path

from admin_web.exercise_analyzer import (
    detect_once,
    simulate_full_reports,
    get_last_report,
    get_engine_library,
    EXR_SETTINGS,
)

bp_exercise = Blueprint("exercise", __name__, url_prefix="/api/exercise")

# ─────────────────────────────────────────────────────────────
# 🧩 settings_dump — מידע בסיסי על המנוע
# ─────────────────────────────────────────────────────────────
def settings_dump() -> Dict[str, Any]:
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


# ─────────────────────────────────────────────────────────────
# 🔹 תרגילים
# ─────────────────────────────────────────────────────────────
@bp_exercise.get("/settings")
def exercise_settings():
    out = settings_dump()
    code = 200 if out.get("ok") else 500
    if out.get("engine", {}).get("available") is False:
        code = 503
    return jsonify(out), code


@bp_exercise.post("/simulate")
def exercise_simulate():
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
    j = request.get_json(silent=True) or {}
    metrics_raw = j.get("metrics")
    if not isinstance(metrics_raw, dict):
        return jsonify(ok=False, error="missing_metrics_object"), 400
    out = detect_once(raw_metrics=metrics_raw, exercise_id=j.get("exercise_id"))
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
    rep = get_last_report()
    return jsonify(ok=bool(rep), report=rep), 200


# ─────────────────────────────────────────────────────────────
# 🔵 דיאגנוסטיקה
# ─────────────────────────────────────────────────────────────
@bp_exercise.get("/diag/stream")
def api_exercise_diag_stream():
    from admin_web.state import get_payload as get_shared_payload
    def snapshot():
        snap = get_shared_payload() or get_last_report() or {}
        metrics = snap.get("metrics") or {}
        return {"ts": int(time.time()), "metrics_keys": list(metrics.keys())[:40]}
    def gen():
        while True:
            yield f"data: {json.dumps(snapshot(), ensure_ascii=False)}\n\n"
            time.sleep(1)
    return Response(stream_with_context(gen()), mimetype="text/event-stream")


@bp_exercise.get("/diag")
def api_exercise_diag_snapshot():
    from admin_web.state import get_payload as get_shared_payload
    snap = get_shared_payload() or get_last_report() or {}
    metrics = snap.get("metrics") or {}
    return jsonify({
        "ts": int(time.time()),
        "metrics_keys": list(metrics.keys())[:40],
        "has_report": bool(get_last_report()),
    }), 200


@bp_exercise.get("/last/json")
def open_last_json():
    rep = get_last_report() or {}
    if not rep:
        return jsonify({"ok": False, "error": "no_last_report"}), 404
    return Response(json.dumps(rep, indent=2, ensure_ascii=False), mimetype="application/json")


@bp_exercise.get("/connection/status")
def connection_status():
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


# ===================================================================
# 🎨 תוויות UI (נכנס כאן — בלי לפתוח קובץ חדש!)
# ===================================================================

_UI_CACHE: Dict[str, Any] = {"metrics": None, "names": None, "ver": None}

def _ui_base() -> Path:
    return Path(__file__).resolve().parents[1] / "exercise_engine" / "report"

def _sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def _load_yaml(p: Path) -> Any:
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def _load_ui_labels(force: bool = False):
    global _UI_CACHE
    if _UI_CACHE["metrics"] and not force:
        return _UI_CACHE
    base = _ui_base()
    metrics_p = base / "metrics_labels.yaml"
    names_p = base / "exercise_names.yaml"
    metrics = _load_yaml(metrics_p)
    names = _load_yaml(names_p)
    ver = _sha1(json.dumps({"metrics": metrics, "names": names}, ensure_ascii=False))
    _UI_CACHE = {"metrics": metrics, "names": names, "ver": ver,
                 "paths": {"metrics": str(metrics_p), "names": str(names_p)}}
    return _UI_CACHE


@bp_exercise.get("/ui/labels")
def ui_all_labels():
    data = _load_ui_labels(force=False)
    return jsonify({
        "ok": True,
        "version": data["ver"],
        "paths": data["paths"],
        "metrics_labels": data["metrics"].get("labels", {}),
        "exercise_names": data["names"].get("names", {}),
    })


@bp_exercise.get("/ui/metrics")
def ui_metrics_labels():
    data = _load_ui_labels(force=False)
    return jsonify({
        "ok": True,
        "version": data["ver"],
        "labels": data["metrics"].get("labels", {}),
        "path": data["paths"]["metrics"],
    })


@bp_exercise.get("/ui/names")
def ui_exercise_names():
    data = _load_ui_labels(force=False)
    return jsonify({
        "ok": True,
        "version": data["ver"],
        "names": data["names"].get("names", {}),
        "path": data["paths"]["names"],
    })


@bp_exercise.post("/ui/reload")
def ui_reload_labels():
    data = _load_ui_labels(force=True)
    return jsonify({
        "ok": True,
        "version": data["ver"],
        "counts": {
            "metrics": len((data["metrics"] or {}).get("labels", {})),
            "exercises": len((data["names"] or {}).get("names", {})),
        },
        "message": "labels reloaded successfully"
    })
