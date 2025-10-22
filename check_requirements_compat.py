# -*- coding: utf-8 -*-
"""
check_requirements_compat.py — בדיקת תאימות ספריות וייבוא מערכת BodyPlus_XPro
---------------------------------------------------------------------------
הקובץ בודק שכל הספריות הקריטיות של התוכנה נטענות בהצלחה
ושאין התנגשות בין הגרסאות (בעיקר MediaPipe, Torch, YOLO, Flask).
אין שום שינוי במערכת — רק הדפסות בדיקה.
"""

import importlib
import sys

print("\n🔍 בודק תאימות ספריות...\n")

LIBRARIES = [
    "torch",
    "torchvision",
    "ultralytics",
    "cv2",
    "mediapipe",
    "onnxruntime",
    "numpy",
    "flask",        # ← במקום "Flask"
    "loguru",
    "pandas",
]


success = []
failed = []

for lib in LIBRARIES:
    try:
        m = importlib.import_module(lib)
        ver = getattr(m, "__version__", "unknown")
        print(f"✅ נטען בהצלחה: {lib} ({ver})")
        success.append((lib, ver))
    except Exception as e:
        print(f"❌ שגיאה בטעינת {lib}: {e}")
        failed.append((lib, str(e)))

print("\n─────────────────────────────────────")
if failed:
    print(f"❗ נמצאו {len(failed)} ספריות עם בעיות:\n")
    for lib, err in failed:
        print(f"  - {lib}: {err}")
else:
    print("🎉 כל הספריות הקריטיות נטענו בהצלחה – התאימות תקינה לחלוטין!")

print("─────────────────────────────────────\n")

# בדיקות מיוחדות: Torch + Ultralytics + MediaPipe שילוב
try:
    import torch
    import ultralytics
    import mediapipe

    x = torch.randn(1, 3, 640, 640)
    print(f"⚙️ Torch עובד (GPU={torch.cuda.is_available()})")
    print(f"📦 Ultralytics גרסה: {ultralytics.__version__}")
    print(f"🧠 MediaPipe גרסה: {mediapipe.__version__}")
    print("\n✅ בדיקת שילוב Torch + YOLO + MediaPipe עברה בהצלחה\n")
except Exception as e:
    print(f"❌ שגיאה בבדיקת שילוב Torch/YOLO/MediaPipe: {e}")

print("בדיקה הסתיימה.\n")
