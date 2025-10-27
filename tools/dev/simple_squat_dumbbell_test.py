# -*- coding: utf-8 -*-
"""
simple_squat_dumbbell_test.py
------------------------------------------------------------
בדיקה פשוטה לתרגיל squat.dumbbell — בלי כל מערכת טעינה חכמה.
הסקריפט:
1. טוען ישירות את קובץ ה־YAML של התרגיל.
2. טוען קובץ ה־base (squat.base.yaml).
3. מחבר אותם.
4. מדפיס את הספים, המשקלים, ורמזי הזיהוי.
------------------------------------------------------------
"""

import os
import yaml
import json

# --- נתיבים ---
ROOT = r"C:\Users\Owner\Desktop\BodyPlus\BodyPlus_XPro"
BASE_FILE = os.path.join(ROOT, "exercise_library", "exercises", "_base", "squat.base.yaml")
VARIANT_FILE = os.path.join(ROOT, "exercise_library", "exercises", "packs", "dumbbell", "squat", "squat_dumbbell.yaml")

# --- פונקציית עזר ---
def load_yaml(path):
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ לא נמצא הקובץ: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

# --- טוען ---
print("📥 טוען קבצי תרגיל...\n")
base = load_yaml(BASE_FILE)
variant = load_yaml(VARIANT_FILE)

# --- מאחד ---
combined = base.copy()
combined.update(variant)

# --- הדפסות ---
print("✅ נטען בהצלחה:")
print(f"  🏷️ ID: {variant.get('id')}")
print(f"  📂 משפחה: {variant.get('family')}")
print(f"  🏋️‍♂️ שם תצוגה: {variant.get('meta', {}).get('display_name')}")
print()

print("⚙️  קריטריונים לניקוד:")
for crit, rule in variant.get("scoring", {}).get("criteria", {}).items():
    print(f"  - {crit} (weight={rule.get('weight', '?')})")

print("\n🔎 רמזים לזיהוי:")
print(json.dumps(variant.get("match_hints", {}), indent=2, ensure_ascii=False))

print("\n📊 דוגמת ניקוד (הדמיה בלבד):")
payload = {
    "knee_left_deg": 90,
    "knee_right_deg": 88,
    "spine_flexion_deg": 8,
    "torso_forward_deg": 20,
    "heel_lift_left": 0,
    "heel_lift_right": 0,
    "rep.timing_s": 1.5
}

score = 0.0
for crit, rule in variant.get("scoring", {}).get("criteria", {}).items():
    w = float(rule.get("weight", 1.0))
    score += w

print(f"\n📈 סה״כ משקל קריטריונים: {score:.2f}")
print("\n✅ סיום בדיקה בהצלחה!\n")
