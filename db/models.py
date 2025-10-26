# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 db/models.py
# מה הקובץ עושה:
#   - יוצר קובץ מסד נתונים (SQLite) ומקים את כל הטבלאות אם חסרות.
#   - נותן פונקציית connect() לעבודה בטוחה עם טרנזאקציה.
# איך משתמשים:
#   - לא מייבאים ישירות בפלואו הראשי; הקבצים האחרים משתמשים ב-connect().
#   - אפשר לשנות מיקום DB דרך משתנה סביבה DB_PATH (ברירת מחדל: db/app.db).
# קלט/פלט:
#   - אין קלט חיצוני; יוצר/פותח קובץ DB ומוסיף טבלאות.
# -----------------------------------------------------------------------------

import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DEFAULT_PATH = os.path.join(BASE_DIR, "app.db")
DB_PATH = os.environ.get("DB_PATH", DEFAULT_PATH)

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  settings_json TEXT
);

CREATE TABLE IF NOT EXISTS workouts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  summary_json TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
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
  FOREIGN KEY(workout_id) REFERENCES workouts(id)
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
  FOREIGN KEY(set_id) REFERENCES sets(id)
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
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
  FOREIGN KEY(workout_id) REFERENCES workouts(id),
  FOREIGN KEY(set_id) REFERENCES sets(id)
);

CREATE INDEX IF NOT EXISTS idx_reports_workout ON reports(workout_id);
CREATE INDEX IF NOT EXISTS idx_reports_set ON reports(set_id);
CREATE INDEX IF NOT EXISTS idx_reports_exercise ON reports(exercise_code);
CREATE INDEX IF NOT EXISTS idx_reports_health ON reports(health_status);
"""

@contextmanager
def connect():
    first = not os.path.exists(DB_PATH)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if first:
        conn.executescript(SCHEMA)
        conn.commit()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
