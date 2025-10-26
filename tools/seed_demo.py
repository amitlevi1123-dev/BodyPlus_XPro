# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# 🇮🇱 tools/seed_demo.py
# מה הקובץ עושה:
#   - יוצר משתמש דמו + אימון + סט + דו״ח דמו קטן, כדי לבדוק שהשמירה וה-API עובדים.
# איך משתמשים:
#   - מריצים:  python -m tools.seed_demo
#   - ואז אפשר לבדוק ב-API: /api/workouts?user_id=1 וכן הלאה.
# קלט/פלט:
#   - אין קלט; מדפיס מזהים למסך ושומר ל-DB.
# -----------------------------------------------------------------------------

from db.saver import ensure_user, start_workout, open_set, close_set, close_workout, save_report_snapshot, save_reps

def main():
    user_id = ensure_user("Amit")
    w_id = start_workout(user_id)
    s_id = open_set(w_id, "squat_bodyweight")

    # דו״ח דמו מינימלי:
    report = {
        "meta": {"payload_version": "1.0"},
        "exercise": {"id": "squat_bodyweight", "display_name": "Squat (BW)"},
        "scoring": {"score": 0.86, "score_pct": 86, "quality": "full", "criteria": []},
        "coverage": {"available_pct": 100},
        "camera": {"visibility_risk": False},
        "reps": [
            {"rep_id": 1, "timing_s": 1.6, "ecc_s": 0.8, "con_s": 0.8, "rom_deg": 95, "score": 0.88},
            {"rep_id": 2, "timing_s": 1.7, "ecc_s": 0.9, "con_s": 0.8, "rom_deg": 92, "score": 0.84}
        ],
        "report_health": {"status": "OK"}
    }

    rep_id = save_report_snapshot(user_id, w_id, s_id, report)
    save_reps(s_id, report["reps"])
    close_set(s_id, score_total_pct=report["scoring"]["score_pct"],
              metrics={"avg_rom_deg": 93.5, "avg_tempo_s": 1.65},
              reps_count=len(report["reps"]))
    close_workout(w_id, summary={"sets": 1, "duration_min": 2, "avg_score_pct": 86})

    print("OK. user_id=", user_id, "workout_id=", w_id, "set_id=", s_id, "report_id=", rep_id)

if __name__ == "__main__":
    main()
