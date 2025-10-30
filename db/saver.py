# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 db/saver.py
# מה הקובץ עושה:
#   • פונקציות קצרות לשמירת ישויות: משתמש / אימון / סט / חזרות / דו"ח מלא.
#   • ממפה את report (מה- build_payload) לשדות תמציתיים בטבלאות.
# שימוש לדוגמה:
#   from db.saver import ensure_user, start_workout, open_set, save_report_snapshot, save_reps, close_set, close_workout
#   uid = ensure_user("Amit")
#   wid = start_workout(uid)
#   sid = open_set(wid, "squat.bodyweight.md")
#   rep_id = save_report_snapshot(uid, wid, sid, report)
#   save_reps(sid, report.get("reps", []))
#   close_set(sid, report["scoring"]["score_pct"], {...}, len(report.get("reps", [])))
#   close_workout(wid, {"sets": 5, "duration_min": 42, "avg_score_pct": 83})
# -----------------------------------------------------------------------------

from __future__ import annotations
from typing import Optional, Dict, Any, List
import json
from .models import connect, now_iso

def _get(d: dict, path: List, default=None):
    """גישה בטוחה לשדות עמוקים בדיקט/רשימה."""
    cur = d
    for p in path:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur):
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
    return cur

# ----------------------- Users -----------------------

def ensure_user(name: str = "Default User") -> int:
    name = (name or "Default User").strip()
    with connect() as c:
        row = c.execute("SELECT id FROM users WHERE name=?", (name,)).fetchone()
        if row:
            return int(row["id"])
        c.execute(
            "INSERT INTO users(name, settings_json, created_at) VALUES (?, ?, ?)",
            (name, json.dumps({}, ensure_ascii=False), now_iso())
        )
        rid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return int(rid)

# ----------------------- Workouts -----------------------

def start_workout(user_id: int) -> int:
    with connect() as c:
        c.execute(
            "INSERT INTO workouts(user_id, started_at) VALUES (?, ?)",
            (int(user_id), now_iso())
        )
        rid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return int(rid)

def close_workout(workout_id: int, summary: Dict[str, Any] | None) -> None:
    with connect() as c:
        c.execute(
            "UPDATE workouts SET ended_at=?, summary_json=? WHERE id=?",
            (now_iso(), json.dumps(summary or {}, ensure_ascii=False), int(workout_id))
        )

# ----------------------- Sets -----------------------

def open_set(workout_id: int, exercise_code: Optional[str]) -> int:
    with connect() as c:
        c.execute(
            "INSERT INTO sets(workout_id, exercise_code, start_ts) VALUES (?, ?, ?)",
            (int(workout_id), exercise_code, now_iso())
        )
        rid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return int(rid)

def close_set(set_id: int,
              score_total_pct: Optional[int],
              metrics: Optional[Dict[str, Any]],
              reps_count: Optional[int]) -> None:
    with connect() as c:
        c.execute(
            """UPDATE sets
               SET end_ts=?, score_total_pct=?, metrics_json=?, reps_count=?
             WHERE id=?""",
            (
                now_iso(),
                int(score_total_pct) if score_total_pct is not None else None,
                json.dumps(metrics or {}, ensure_ascii=False),
                int(reps_count) if reps_count is not None else None,
                int(set_id),
            )
        )

# ----------------------- Reps -----------------------

def save_reps(set_id: int, reps: List[Dict[str, Any]] | list) -> None:
    """שומר חזרות לסט. תואם לשדות שמופיעים ב-report['reps']."""
    if not isinstance(reps, list) or not reps:
        return
    rows = []
    for idx, r in enumerate(reps, start=1):
        rep_index = int(r.get("rep_id") or idx)
        timing_s  = r.get("timing_s")
        ecc_s     = r.get("ecc_s")
        con_s     = r.get("con_s")
        # ROM יכול להיקרא rom_deg או rom
        rom_val   = r.get("rom_deg") if "rom_deg" in r else r.get("rom")
        rom_units = "deg" if "rom_deg" in r else r.get("rom_units")
        score     = r.get("score")
        quality_pct = int(round(float(score) * 100)) if isinstance(score, (int, float)) else None
        labels    = r.get("labels") if isinstance(r.get("labels"), list) else []
        rows.append((
            int(set_id), rep_index, timing_s, ecc_s, con_s,
            rom_val, rom_units, quality_pct,
            json.dumps(labels, ensure_ascii=False)
        ))
    with connect() as c:
        c.executemany(
            """INSERT INTO reps
               (set_id, rep_index, timing_s, ecc_s, con_s, rom, rom_units, quality_pct, labels_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            rows
        )

# ----------------------- Reports -----------------------

def save_report_snapshot(user_id: int,
                         workout_id: int,
                         set_id: Optional[int],
                         report: Dict[str, Any]) -> int:
    """
    שומר תמונת דו״ח מלאה (JSON) + שדות סיכום עיקריים לשאילתות מהירות.
    """
    exercise_code = _get(report, ["exercise", "id"])
    score_pct     = _get(report, ["scoring", "score_pct"])
    quality       = _get(report, ["scoring", "quality"])
    coverage_pct  = _get(report, ["coverage", "available_pct"])
    camera_risk   = 1 if bool(_get(report, ["camera", "visibility_risk"], False)) else 0
    health_status = _get(report, ["report_health", "status"])
    payload_ver   = _get(report, ["meta", "payload_version"])
    created_at    = now_iso()

    with connect() as c:
        c.execute(
            """INSERT INTO reports(
                   user_id, workout_id, set_id, created_at, exercise_code, score_pct, quality,
                   coverage_pct, camera_risk, health_status, payload_version, report_json
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(user_id), int(workout_id), int(set_id) if set_id is not None else None,
                created_at, exercise_code,
                int(score_pct) if score_pct is not None else None,
                quality,
                int(coverage_pct) if coverage_pct is not None else None,
                int(camera_risk),
                health_status,
                payload_ver,
                json.dumps(report, ensure_ascii=False)
            )
        )
        rid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        return int(rid)
