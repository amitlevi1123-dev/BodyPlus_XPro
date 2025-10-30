# -*- coding: utf-8 -*-
"""
admin_web/routes_exercise.py
----------------------------
ראוטים רזים ל-Exercise API, משתמשים בלוגיקה שב-admin_web/exercise_analyzer.py.

Endpoints:
- GET    /api/exercise/settings
- POST   /api/exercise/reload_labels
- GET    /api/exercise/labels
- POST   /api/exercise/simulate
- POST   /api/exercise/score
- POST   /api/exercise/detect
- GET    /api/exercise/last
- GET    /api/exercise/last/json
- POST   /api/exercise/pick
"""

from __future__ import annotations
from typing import Dict, Any
from flask import Blueprint, jsonify, request, Response
import json, time

from admin_web.exercise_analyzer import (
    settings_dump,
    simulate_exercise,
    analyze_exercise,
    detect_once,
    get_last_report,
    set_last_report,
    reload_ui_labels,
    get_ui_labels,
)

bp_exercise = Blueprint("exercise", __name__, url_prefix="/api/exercise")

# ─────────────────────────────────────────────────────────────
# תוויות/הגדרות
# ─────────────────────────────────────────────────────────────
@bp_exercise.get("/settings")
def exercise_settings():
    return jsonify(settings_dump()), 200

@bp_exercise.post("/reload_labels")
def exercise_reload_labels():
    out = reload_ui_labels()
    return jsonify(out), (200 if out.get("ok") else 500)

@bp_exercise.get("/labels")
def exercise_labels():
    return jsonify(get_ui_labels()), 200

# ─────────────────────────────────────────────────────────────
# סימולציה
# ─────────────────────────────────────────────────────────────
@bp_exercise.post("/simulate")
def exercise_simulate():
    j = request.get_json(silent=True) or {}
    out = simulate_exercise(
        sets=int(j.get("sets", 2)),
        reps=int(j.get("reps", 5)),
        mode=j.get("mode", "mixed"),
        noise=float(j.get("noise", 0.2)),
        mean_score=float(j.get("mean_score", 0.75)),
        std=float(j.get("std", 0.10)),
        seed=j.get("seed", 42),
    )

    # נשמור כברירת מחדל את הדו"ח האחרון של הסט/חזרה האחרונים עבור מודאל "פרטים"
    try:
        sets_list = out.get("sets") or []
        if sets_list:
            reps_list = (sets_list[-1] or {}).get("reps") or []
            if reps_list:
                rep_report = (reps_list[-1] or {}).get("report")
                if isinstance(rep_report, dict):
                    set_last_report(rep_report)
    except Exception:
        pass

    return jsonify(out), 200

# ─────────────────────────────────────────────────────────────
# ניקוד "שירות" ללא המנוע (כפתור "ניקוד (שירות)")
# ─────────────────────────────────────────────────────────────
@bp_exercise.post("/score")
def exercise_score():
    j = request.get_json(silent=True) or {}
    metrics = j.get("metrics")
    if not isinstance(metrics, dict):
        return jsonify(ok=False, error="no_metrics"), 400
    result = analyze_exercise({"metrics": metrics, "exercise": j.get("exercise") or {}})
    return jsonify(result), 200

# ─────────────────────────────────────────────────────────────
# זיהוי אמיתי דרך מנוע
# ─────────────────────────────────────────────────────────────
@bp_exercise.post("/detect")
def exercise_detect():
    j = request.get_json(silent=True) or {}
    metrics_raw = j.get("metrics")
    if not isinstance(metrics_raw, dict):
        return jsonify(ok=False, error="missing_metrics_object"), 400

    out = detect_once(raw_metrics=metrics_raw, exercise_id=j.get("exercise_id"))
    if out.get("ok") and isinstance(out.get("report"), dict):
        try: set_last_report(out["report"])
        except Exception: pass

    if out.get("ok"):
        return jsonify(out), 200
    err = (out.get("error") or "").lower()
    if "engine_unavailable" in err: return jsonify(out), 503
    if "library_load_failed" in err: return jsonify(out), 500
    if "runtime_failed" in err: return jsonify(out), 500
    return jsonify(out), 500

# ─────────────────────────────────────────────────────────────
# דו"ח אחרון (מודאל "פרטים")
# ─────────────────────────────────────────────────────────────
@bp_exercise.get("/last")
def exercise_last():
    rep = get_last_report()
    return jsonify(ok=bool(rep), report=rep), 200

@bp_exercise.get("/last/json")
def open_last_json():
    rep = get_last_report() or {}
    if not rep:
        return jsonify({"ok": False, "error": "no_last_report"}), 404
    return Response(json.dumps(rep, indent=2, ensure_ascii=False), mimetype="application/json")

# ─────────────────────────────────────────────────────────────
# בחירת דו"ח מסימולציה (אופציונלי)
# ─────────────────────────────────────────────────────────────
@bp_exercise.post("/pick")
def exercise_pick():
    j = request.get_json(silent=True) or {}
    result = j.get("result") or {}
    set_idx = int(j.get("set", -1))
    rep_idx = int(j.get("rep", -1))
    try:
        sets_list = result.get("sets") or []
        if not sets_list: return jsonify(ok=False, error="no_sets"), 400
        if set_idx < 0: set_idx = len(sets_list) + set_idx
        set_idx = max(0, min(set_idx, len(sets_list) - 1))
        reps_list = (sets_list[set_idx] or {}).get("reps") or []
        if not reps_list: return jsonify(ok=False, error="no_reps"), 400
        if rep_idx < 0: rep_idx = len(reps_list) + rep_idx
        rep_idx = max(0, min(rep_idx, len(reps_list) - 1))
        report = (reps_list[rep_idx] or {}).get("report")
        if not isinstance(report, dict): return jsonify(ok=False, error="no_report"), 400
        set_last_report(report)
        return jsonify(ok=True), 200
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500
