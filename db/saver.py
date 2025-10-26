# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 db/saver.py
# מה הקובץ עושה:
#   - מספק פונקציות קצרות שמנהלות אימון/סט/חזרות ושומרות דו״ח מלא (JSON).
# איך משתמשים:
#   - import מהקוד שלך, וקוראים לפונקציות בזמן אמת:
#       user_id = ensure_user("Amit")
#       w_id = start_workout(user_id)
#       s_id = open_set(w_id, "squat_bodyweight")
#       report_id = save_report_snapshot(user_id, w_id, s_id, report)
#       save_reps(s_id, report.get("reps", []))
#       close_set(s_id, report["scoring"]["score_pct"], {...}, len(report.get("reps", [])))
#       close_workout(w_id, {"sets": 5, "duration_min": 42, "avg_score_pct": 83})
# קלט/פלט:
#   - קלט: נתונים פשוטים או אובייקט report (כמו שיוצא מ-build_payload).
#   - פלט: מזהים (IDs) שנוצרים במסד.
# -----------------------------------------------------------------------------

from typing import Optional, Dict, Any, List
import json
from .models import connect, now_iso

def _get(d: dict, path: List, default=None):
    cur = d
    for p in path:
        if isinstance(p, int):  # גישה לרשימה
            if not isinstance(cur, list) or p >= len(cur):
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
    return cur

def ensure_user(name: str = "Default User") -> int:
    with connect() as c:
        row = c.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        c.execute("INSERT INTO users(name, settings_json) VALUES (?, ?)", (name, json.dumps({})))
        return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

def start_workout(user_id: int) -> int:
    with connect() as c:
        c.execute("INSERT INTO workouts(user_id, started_at) VALUES (?, ?)", (user_id, now_iso()))
        return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

def close_workout(workout_id: int, summary: dict):
    with connect() as c:
        c.execute("UPDATE workouts SET ended_at=?, summary_json=? WHERE id=?",
                  (now_iso(), json.dumps(summary or {}, ensure_ascii=False), workout_id))

def open_set(workout_id: int, exercise_code: Optional[str]) -> int:
    with connect() as c:
        c.execute("INSERT INTO sets(workout_id, exercise_code, start_ts) VALUES (?, ?, ?)",
                  (workout_id, exercise_code, now_iso()))
        return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

def close_set(set_id: int, score_total_pct: Optional[int], metrics: Optional[dict], reps_count: Optional[int]):
    with connect() as c:
        c.execute("""UPDATE sets
                     SET end_ts=?, score_total_pct=?, metrics_json=?, reps_count=?
                     WHERE id=?""",
                  (now_iso(),
                   int(score_total_pct) if score_total_pct is not None else None,
                   json.dumps(metrics or {}, ensure_ascii=False),
                   int(reps_count) if reps_count is not None else None,
                   set_id))

def save_reps(set_id: int, reps: list):
    if not isinstance(reps, list) or not reps:
        return
    with connect() as c:
        for idx, r in enumerate(reps, start=1):
            labels = r.get("labels") if isinstance(r.get("labels"), list) else []
            score = r.get("score")
            quality_pct = int(round(score * 100)) if isinstance(score, (int, float)) else None
            rom_val = r.get("rom_deg") if "rom_deg" in r else r.get("rom")
            rom_units = "deg" if "rom_deg" in r else r.get("rom_units")
            c.execute("""INSERT INTO reps
                        (set_id, rep_index, timing_s, ecc_s, con_s, rom, rom_units, quality_pct, labels_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (set_id,
                       int(r.get("rep_id", idx)),
                       r.get("timing_s"),
                       r.get("ecc_s"),
                       r.get("con_s"),
                       rom_val,
                       rom_units,
                       quality_pct,
                       json.dumps(labels, ensure_ascii=False)))

def save_report_snapshot(user_id: int, workout_id: int, set_id: Optional[int], report: dict) -> int:
    exercise_code = _get(report, ["exercise", "id"])
    score_pct = _get(report, ["scoring", "score_pct"])
    quality = _get(report, ["scoring", "quality"])
    coverage_pct = _get(report, ["coverage", "available_pct"])
    camera_risk = 1 if bool(_get(report, ["camera", "visibility_risk"], False)) else 0
    health_status = _get(report, ["report_health", "status"])
    payload_version = _get(report, ["meta", "payload_version"])
    created_at = now_iso()

    with connect() as c:
        c.execute("""INSERT INTO reports
            (workout_id, set_id, created_at, exercise_code, score_pct, quality,
             coverage_pct, camera_risk, health_status, payload_version, report_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (workout_id,
             set_id,
             created_at,
             exercise_code,
             int(score_pct) if score_pct is not None else None,
             quality,
             int(coverage_pct) if coverage_pct is not None else None,
             camera_risk,
             health_status,
             payload_version,
             json.dumps(report, ensure_ascii=False)))
        return c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
