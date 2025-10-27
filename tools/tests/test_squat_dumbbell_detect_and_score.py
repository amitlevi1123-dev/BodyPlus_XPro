# -*- coding: utf-8 -*-
"""
בדיקה עצמאית ל-squat.dumbbell בייבוא נקי מחבילה exercise_engine
"""

import os, sys, json

# להכניס את שורש הפרויקט ל-sys.path (ליתר ביטחון, בנוסף ל-PYTHONPATH)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from exercise_engine.runtime import runtime_loader
from exercise_engine.classifier import classifier
from exercise_engine.scoring import scoring

print("🚀 בדיקת זיהוי וניקוד של squat.dumbbell")

# 1) טען ספריית תרגילים
library = runtime_loader.load_library()

# 2) Payload לדוגמה
payload = {
    "pose.available": True,
    "objdet.dumbbell_present": True,
    "objdet.bar_present": False,
    "knee_left_deg": 90,
    "knee_right_deg": 88,
    "torso_forward_deg": 20,
    "spine_flexion_deg": 8,
    "spine_curvature_side_deg": 3,
    "knee_foot_alignment_left_deg": 4,
    "knee_foot_alignment_right_deg": 5,
    "features.stance_width_ratio": 1.0,
    "toe_angle_left_deg": 12,
    "toe_angle_right_deg": 13,
    "rep.timing_s": 1.5,
    "heel_lift_left": 0,
    "heel_lift_right": 0,
}

# 3) זיהוי
res = classifier.pick(payload, library)
print("\n🔎 זיהוי תרגיל:")
print(f"  ➤ exercise_id: {res.exercise_id}")
print(f"  ➤ confidence:  {res.confidence:.2f}")
print(f"  ➤ reason:      {res.reason}")
print(f"  ➤ inferred eq: {res.equipment_inferred}")

# 4) ניקוד
exercise = library.get(res.exercise_id)
report = scoring.score_exercise(payload, exercise)

print("\n📊 תוצאות ניקוד:")
print(json.dumps(report, indent=2, ensure_ascii=False))

score_total = report.get("score_total", 0.0)
print("\n🏁 סיכום:")
print(f"  ➤ ציון כולל: {round(score_total, 3)}")
if score_total >= 0.85:
    print("  ✅ טכניקה מצוינת!")
elif score_total >= 0.7:
    print("  🙂 טכניקה טובה, יש מקום לשיפור קל.")
else:
    print("  ⚠️ הציון נמוך — בדוק יציבה/עומק/עקבים.")
print("\n✅ סיום בדיקה.\n")
