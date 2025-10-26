# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 db/models.py
# מה הקובץ עושה:
#   • פותח חיבור ל-SQLite עם Row factory.
#   • יוצר את הסכימה אם חסרה (טבלאות + אינדקסים).
#   • מפעיל FOREIGN KEYS על כל חיבור.
#   • מספק connect() כ-context manager ו-now_iso() לתאריכים.
# קונפיג:
#   • DB_PATH דרך משתנה סביבה (ברירת מחדל: db/app.db).
# -----------------------------------------------------------------------------

from __future__ import annotations
import os, sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

BASE_DIR = os.path.dirname(__file__)
DEFAULT_PATH = os.path.abspath(os.path.join(BASE_DIR, "app.db"))
DB_PATH = os.environ.get("DB_PATH", DEFAULT_PATH)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  settings_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary_json TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workout_id INTEGER NOT NULL,
  exercise_code TEXT,
  start_ts TEXT,
  end_ts TEXT,
  score_total_pct INTEGER,
  metrics_json TEXT,
  reps_count INTEGER,
  FOREIGN KEY(workout_id) REFERENCES workouts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  set_id INTEGER NOT NULL,
  rep_index INTEGER,
  timing_s REAL,
  ecc_s REAL,
  con_s REAL,
  rom REAL,
  rom_units TEXT,
  quality_pct INTEGER,
  labels_json TEXT,
  FOREIGN KEY(set_id) REFERENCES sets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  workout_id INTEGER,
  set_id INTEGER,
  created_at TEXT NOT NULL,
  exercise_code TEXT,
  score_pct INTEGER,
  quality TEXT,
  coverage_pct INTEGER,
  camera_risk INTEGER,
  health_status TEXT,
  payload_version TEXT,
  report_json TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
  FOREIGN KEY(workout_id) REFERENCES workouts(id) ON DELETE SET NULL,
  FOREIGN KEY(set_id) REFERENCES sets(id) ON DELETE SET NULL
);

-- אינדקסים לשאילתות מהירות
CREATE INDEX IF NOT EXISTS idx_workouts_user_started ON workouts(user_id, datetime(started_at) DESC);
CREATE INDEX IF NOT EXISTS idx_sets_workout_start ON sets(workout_id, datetime(start_ts) ASC);
CREATE INDEX IF NOT EXISTS idx_reps_set_index ON reps(set_id, rep_index);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_workout ON reports(workout_id);
CREATE INDEX IF NOT EXISTS idx_reports_set ON reports(set_id);
CREATE INDEX IF NOT EXISTS idx_reports_exercise ON reports(exercise_code);
CREATE INDEX IF NOT EXISTS idx_reports_health ON reports(health_status);
"""

def now_iso() -> str:
    """תאריך־שעה בפורמט ISO-8601 עם Z."""
    return datetime.utcnow().isoformat() + "Z"

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()

@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """
    שימוש:
        from db.models import connect
        with connect() as c:
            rows = c.execute("SELECT ...").fetchall()
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    first_time = not os.path.exists(DB_PATH)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # חשוב: להבטיח מפתחות זרים פעילים בכל חיבור
    conn.execute("PRAGMA foreign_keys=ON;")

    if first_time:
        _ensure_schema(conn)

    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
