# -*- coding: utf-8 -*-
"""
count_lines.py — סופר את כל שורות הקוד בפרויקט BodyPlus_XPro
--------------------------------------------------------------
מה הוא עושה:
• עובר על כל התיקיות שבתוך התיקייה הנוכחית (רק אם יש בהן קבצים רלוונטיים)
• סופר שורות בכל קובץ קוד (python, js, html, css, yaml וכו')
• מדלג על תיקיות וירטואליות או קבצי ביניים (.venv, __pycache__, וכו')
• בסוף מדפיס סיכום כללי + פירוט לכל סוג קובץ
"""

import os

# סוגי קבצים שנספר
EXTS = (".py", ".js", ".html", ".css", ".yaml", ".yml", ".json")

EXCLUDE_DIRS = {".venv", "__pycache__", "node_modules", ".git"}

def count_lines_in_file(path: str) -> int:
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0

def count_all_lines(base_dir: str):
    totals = {}
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            ext = os.path.splitext(file)[1].lower()
            if ext in EXTS:
                path = os.path.join(root, file)
                lines = count_lines_in_file(path)
                totals[ext] = totals.get(ext, 0) + lines
    total_lines = sum(totals.values())
    print(f"\n📊 סיכום שורות קוד בפרויקט: {base_dir}")
    print("────────────────────────────────────────────")
    for ext, count in sorted(totals.items()):
        print(f"{ext:<8} : {count:>6} שורות")
    print("────────────────────────────────────────────")
    print(f"סה״כ שורות קוד בכל הקבצים: {total_lines:,}")
    print()

if __name__ == "__main__":
    count_all_lines(".")
