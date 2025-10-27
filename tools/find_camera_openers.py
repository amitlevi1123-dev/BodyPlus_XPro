# -*- coding: utf-8 -*-
"""
find_camera_openers.py — מאתר קטעי קוד שמנסים לפתוח מצלמה (cv2.VideoCapture)
---------------------------------------------------------------------------
סריקה אוףליין של כל קובצי .py בפרויקט כדי למצוא מקומות
שבהם מתבצעת פתיחת מצלמה — ישירה או עקיפה.

איך להריץ:
    python tools/find_camera_openers.py

מה תקבל:
    - רשימת קבצים ושורות חשודות
    - סיכום כולל כמה קריאות נמצאו
"""

import os
import re

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CAMERA_PATTERNS = [
    r"cv2\.VideoCapture\s*\(",
    r"VideoCapture\s*\(",
    r"cv2\.VideoCapture\(\s*[0-9]",
    r"cv2\.VideoCapture\(\s*['\"]",
    r"camera\s*=\s*cv2\.",
]

def scan_file(path):
    results = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f, start=1):
                for pat in CAMERA_PATTERNS:
                    if re.search(pat, line):
                        results.append((i, line.strip()))
                        break
    except Exception as e:
        print(f"[!] שגיאה בקריאת {path}: {e}")
    return results

def main():
    hits = []
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            if file.endswith(".py"):
                full = os.path.join(root, file)
                found = scan_file(full)
                if found:
                    hits.append((full, found))

    print("\n=== 🔍 דו\"ח פתיחות מצלמה (cv2.VideoCapture) ===\n")
    if not hits:
        print("✅ לא נמצאו קריאות ל-cv2.VideoCapture.\n")
        return

    for fpath, lines in hits:
        print(f"📂 {os.path.relpath(fpath, ROOT_DIR)}")
        for lineno, code in lines:
            print(f"  {lineno:4d}: {code}")
        print("-" * 60)
    print(f"\nסה\"כ {sum(len(v) for _, v in hits)} מופעים שנמצאו.\n")

if __name__ == "__main__":
    main()
