# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 admin_web/routes_data_api.py
# מה הקובץ עושה:
#   - מספק 3 API-ים בסיסיים לקריאה מהאפליקציה/אדמין:
#       1) רשימת אימונים למשתמש
#       2) הסטים של אימון
#       3) דו״ח מלא לפי סט (JSON שנשמר)
# איך משתמשים:
#   - לרשום את ה-blueprint באפליקציית Flask הראשית.
#   - לקרוא מהאפליקציה (Flutter) את ה-JSON ולייצר מסכים/גרפים.
# קלט/פלט:
#   - קלט: פרמטרים ב-GET (user_id, workout_id, set_id).
#   - פלט: JSON פשוט ונקי.
# -----------------------------------------------------------------------------

from flask import Blueprint, jsonify, request, abort
from db.models import connect

bp_data = Blueprint("data_api", __name__, url_prefix="/api")

@bp_data.get("/workouts")
def list_workouts():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        abort(400, "user_id is required")
    with connect() as c:
        rows = c.execute("""
            SELECT id, started_at, ended_at, summary_json
            FROM workouts
            WHERE user_id=?
            ORDER BY datetime(started_at) DESC
        """, (user_id,)).fetchall()
    out = []
    import json, math
    for r in rows:
        summary = {}
        if r["summary_json"]:
            try:
                summary = json.loads(r["summary_json"])
            except Exception:
                summary = {}
        out.append({
            "workout_id": r["id"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "summary": summary
        })
    return jsonify(out)

@bp_data.get("/workouts/<int:workout_id>/sets")
def list_sets(workout_id: int):
    with connect() as c:
        rows = c.execute("""
            SELECT id, exercise_code, start_ts, end_ts, score_total_pct, reps_count
            FROM sets
            WHERE workout_id=?
            ORDER BY datetime(start_ts) ASC
        """, (workout_id,)).fetchall()
    out = []
    for r in rows:
        out.append({
            "set_id": r["id"],
            "exercise_code": r["exercise_code"],
            "start_ts": r["start_ts"],
            "end_ts": r["end_ts"],
            "score_total_pct": r["score_total_pct"],
            "reps_count": r["reps_count"],
        })
    return jsonify(out)

@bp_data.get("/sets/<int:set_id>/report")
def get_set_report(set_id: int):
    with connect() as c:
        row = c.execute("""
            SELECT report_json
            FROM reports
            WHERE set_id=?
            ORDER BY datetime(created_at) DESC
            LIMIT 1
        """, (set_id,)).fetchone()
    if not row:
        abort(404, "report not found for set")
    import json
    try:
        payload = json.loads(row["report_json"])
    except Exception:
        payload = {"error": "invalid report_json"}
    return jsonify(payload)
