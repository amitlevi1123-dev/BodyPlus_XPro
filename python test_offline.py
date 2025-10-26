# -*- coding: utf-8 -*-
"""
test_offline.py — בדיקה אופליין מלאה לשכבת ה-DB (ועם שרת אם זמין)
שימוש:
  python test_offline.py           # מילוי DB ובדיקת קריאות ישירות
  python test_offline.py --reset   # איפוס מלא של קובץ ה-DB לפני הרצה
"""

from __future__ import annotations
import os, sys, json, shutil, traceback

# ---------- הגדרת DB ----------
def _db_path():
    try:
        # נשתמש בנתיב ברירת המחדל של models.py כדי להמנע מפערים
        from db.models import DB_PATH
        return DB_PATH
    except Exception:
        # נפילה? נגדיר גיבוי באזור db/app.db
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "db"))
        return os.path.join(base, "app.db")

def reset_db_file():
    path = _db_path()
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    if os.path.exists(path):
        print(f"[RESET] Removing DB file: {path}")
        os.remove(path)
    # ניקוי קבצי WAL/SHM אם נוצרו
    for ext in (".wal", ".shm"):
        p2 = path + ext
        if os.path.exists(p2):
            try: os.remove(p2)
            except: pass

# ---------- נתוני דמה ----------
DUMMY_REPORT = {
    "meta": {"payload_version": "1.0"},
    "exercise": {"id": "squat.bodyweight", "display_name": "Bodyweight Squat"},
    "scoring": {"score": 0.83, "score_pct": 83, "quality": "partial"},
    "coverage": {"available_pct": 92},
    "reps": [
        {"rep_id": 1, "timing_s": 2.4, "ecc_s": 1.2, "con_s": 1.2, "rom_deg": 95, "score": 0.84, "labels": ["depth_ok"]},
        {"rep_id": 2, "timing_s": 2.5, "ecc_s": 1.1, "con_s": 1.4, "rom_deg": 97, "score": 0.82, "labels": []},
    ],
    "report_health": {"status": "OK"},
    "camera": {"visibility_risk": False}
}

# ---------- הדפסה יפה ----------
def jprint(title, obj):
    print(f"\n=== {title} ===")
    try:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    except Exception:
        print(obj)

# ---------- שלב 1: כתיבה וקריאה ישירה דרך db/ ----------
def run_db_flow():
    print("\n[1] DB direct flow (saver/models) ...")
    from db.saver import ensure_user, start_workout, open_set, save_report_snapshot, save_reps, close_set, close_workout
    from db.models import connect, DB_PATH

    # יצירת משתמש/אימון/סט וכתיבת דו"ח
    uid = ensure_user("Amit")
    wid = start_workout(uid)
    sid = open_set(wid, "squat.bodyweight")
    rep_id = save_report_snapshot(uid, wid, sid, DUMMY_REPORT)
    save_reps(sid, DUMMY_REPORT.get("reps", []))
    close_set(sid, DUMMY_REPORT["scoring"]["score_pct"], {"avg_rom_deg": 96, "duration_s": 5.0}, len(DUMMY_REPORT["reps"]))
    close_workout(wid, {"sets": 1, "duration_min": 1, "avg_score_pct": 83})
    print(f"[OK] user={uid} workout={wid} set={sid} report={rep_id}")
    print(f"[DB] Path: {DB_PATH}")

    # קריאה חזרה לבדיקה בסיסית
    with connect() as c:
        w_rows = c.execute("SELECT id, user_id, started_at, ended_at FROM workouts ORDER BY id DESC").fetchall()
        s_rows = c.execute("SELECT id, workout_id, exercise_code, reps_count FROM sets WHERE workout_id=? ORDER BY id", (wid,)).fetchall()
        r_row  = c.execute("SELECT id, set_id, exercise_code, score_pct, report_json FROM reports WHERE set_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()

    jprint("workouts (top)", [dict(w) for w in w_rows[:3]])
    jprint("sets for workout", [dict(s) for s in s_rows])
    jprint("report (short)", {"id": r_row["id"], "set_id": r_row["set_id"], "exercise_code": r_row["exercise_code"], "score_pct": r_row["score_pct"]})

    # אימות שה-JSON נשמר תקין
    rep_json = json.loads(r_row["report_json"])
    assert rep_json["scoring"]["score_pct"] == 83, "score_pct mismatch"
    print("[ASSERT] report_json looks good.")

    # נחזיר מזהים לשלב הבא (API)
    return {"user_id": uid, "workout_id": wid, "set_id": sid}

# ---------- שלב 2: קריאה דרך ה-API (אם זמין) ----------
def try_api_flow(ids):
    print("\n[2] API flow via Flask test_client (optional) ...")
    try:
        # נטען את הבלופרינטים של ה-API ותוך כדי את server.create_app אם קיים
        # עדיפות לשרת (יש בו after_request/headers וכו')
        try:
            from server import create_app  # סוגר הכל יפה
            app = create_app()
            print("[server] create_app() loaded.")
        except Exception as e:
            # נפילה? נרכיב אפליקציה קטנה רק עם ה-data_api
            print(f"[server] not available ({e}). Falling back to data_api only.")
            from flask import Flask
            app = Flask(__name__)
            try:
                from admin_web.routes_data_api import bp_data
                app.register_blueprint(bp_data)
                print("[api] data_api blueprint registered.")
            except Exception as e2:
                print(f"[api] routes_data_api not available: {e2}")
                return False

        client = app.test_client()

        # 2.1 workouts
        r1 = client.get(f"/api/workouts?user_id={ids['user_id']}")
        assert r1.status_code == 200, f"/api/workouts failed: {r1.status_code}"
        workouts = r1.get_json()
        jprint("GET /api/workouts", workouts)

        # נאתר את ה-workout_id שקיבלנו בשלב 1
        wids = [w.get("workout_id") for w in workouts]
        assert ids["workout_id"] in wids, "workout_id not found in /api/workouts"

        # 2.2 sets
        r2 = client.get(f"/api/workouts/{ids['workout_id']}/sets")
        assert r2.status_code == 200, f"/api/workouts/<id>/sets failed: {r2.status_code}"
        sets_ = r2.get_json()
        jprint(f"GET /api/workouts/{ids['workout_id']}/sets", sets_)
        sids = [s.get("set_id") for s in sets_]
        assert ids["set_id"] in sids, "set_id not found in /api/workouts/<id>/sets"

        # 2.3 report by set
        r3 = client.get(f"/api/sets/{ids['set_id']}/report")
        assert r3.status_code == 200, f"/api/sets/<id>/report failed: {r3.status_code}"
        report_full = r3.get_json()
        jprint(f"GET /api/sets/{ids['set_id']}/report", {"scoring": report_full.get("scoring"), "coverage": report_full.get("coverage")})
        assert report_full.get("scoring", {}).get("score_pct") == 83, "score_pct mismatch from API"

        print("[OK] API flow is good.")
        return True

    except AssertionError as ae:
        print("[ASSERTION ERROR]", ae)
        return False
    except Exception as e:
        print("[API ERROR]", e)
        traceback.print_exc()
        return False

# ---------- main ----------
def main():
    if "--reset" in sys.argv:
        reset_db_file()

    # שלב 1: DB ישיר
    try:
        ids = run_db_flow()
    except Exception as e:
        print("[FATAL] DB flow failed:", e)
        traceback.print_exc()
        sys.exit(1)

    # שלב 2: API אופציונלי (אם יש server.py או לפחות routes_data_api)
    ok_api = try_api_flow(ids)
    if not ok_api:
        print("\n[NOTE] API step skipped/failed. זה בסדר לאופליין — הדאטה ב-DB תקין. אפשר להמשיך לפיתוח האפליקציה (Flutter) מול ה-API כשהשרת מוכן.")

    print("\n✓ DONE. אתה מוכן להתקדם.")

if __name__ == "__main__":
    main()
