# -*- coding: utf-8 -*-
"""
בדיקת תצורה אופליין: פורטים, app.run, ונתיבי healthz
=====================================================
מה בודק?
- הופעות של 'app.run(' ו-'port=5000/8000' בכל קובצי .py
- הופעות של 'gunicorn' בקבצים (Dockerfile*, *.sh, *.ps1, *.bat, requirements, README)
- האם מוגדרים נתיבי '/healthz' או '/readyz' באפליקציה/Blueprint
- חיפוש רמזים לפורט קשיח (":5000", ":8000") בקוד

שימוש:
    python tools/offline_port_health_audit.py
"""

from __future__ import annotations
import os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # פרויקט
INCLUDE_EXT = {".py", ".sh", ".ps1", ".bat", ".txt", ".md", ".yml", ".yaml", ".ini", ".cfg", ".toml", ".Dockerfile"}
SPECIAL_NAMES = {"Dockerfile", "Dockerfile.dev", "Procfile", "requirements.txt", "README.md"}

PY_PATTERNS = {
    "app_run": re.compile(r"\bapp\.run\s*\("),
    "port_5000_kw": re.compile(r"port\s*=\s*5000\b"),
    "port_8000_kw": re.compile(r"port\s*=\s*8000\b"),
    "healthz_route": re.compile(r'@.*route\(["\']\/healthz["\']'),
    "readyz_route": re.compile(r'@.*route\(["\']\/readyz["\']'),
    "blueprint_healthz": re.compile(r'Blueprint|bp_.*|register_blueprint'),
}

GEN_PATTERNS = {
    "gunicorn": re.compile(r"\bgunicorn\b"),
    "bind_5000": re.compile(r"0\.0\.0\.0:5000|:5000\b"),
    "bind_8000": re.compile(r"0\.0\.0\.0:8000|:8000\b"),
}

def iter_files():
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        if p.name in {".venv", "__pycache__"}:
            continue
        if any(part in {".venv", "__pycache__", ".git"} for part in p.parts):
            continue
        if p.suffix in INCLUDE_EXT or p.name in SPECIAL_NAMES or p.suffix == "":
            yield p

def scan_file(path: Path):
    try:
        txt = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    findings = []
    if path.suffix == ".py":
        for key, pat in PY_PATTERNS.items():
            for m in pat.finditer(txt):
                line_no = txt[:m.start()].count("\n") + 1
                findings.append((key, line_no, m.group(0)))
    # חפש גם תבניות כלליות
    for key, pat in GEN_PATTERNS.items():
        for m in pat.finditer(txt):
            line_no = txt[:m.start()].count("\n") + 1
            findings.append((key, line_no, m.group(0)))
    return findings

def main():
    print("==============================================")
    print(" BodyPlus_XPro • Offline Port & Health Audit")
    print(" Root:", ROOT)
    print("==============================================\n")

    results = {}
    for f in iter_files():
        finds = scan_file(f)
        if finds:
            results[f] = finds

    # סיכומים
    app_run_hits = []
    port5000_kw = []
    port8000_kw = []
    healthz_hits = []
    readyz_hits = []
    gunicorn_hits = []
    bind5000_hits = []
    bind8000_hits = []

    for f, finds in results.items():
        for key, line, snippet in finds:
            rec = (str(f.relative_to(ROOT)), line, snippet.strip())
            if key == "app_run": app_run_hits.append(rec)
            elif key == "port_5000_kw": port5000_kw.append(rec)
            elif key == "port_8000_kw": port8000_kw.append(rec)
            elif key == "healthz_route": healthz_hits.append(rec)
            elif key == "readyz_route": readyz_hits.append(rec)
            elif key == "gunicorn": gunicorn_hits.append(rec)
            elif key == "bind_5000": bind5000_hits.append(rec)
            elif key == "bind_8000": bind8000_hits.append(rec)

    def section(title, items):
        print(f"\n--- {title} ---")
        if not items:
            print("  (אין ממצאים)")
        else:
            for rel, ln, snip in items:
                print(f"  {rel}:{ln} | {snip}")

    section("app.run(...) נמצאו", app_run_hits)
    section("port=5000 בקוד Python", port5000_kw)
    section("port=8000 בקוד Python", port8000_kw)
    section("נתיב /healthz", healthz_hits)
    section("נתיב /readyz", readyz_hits)
    section("אזכורי gunicorn", gunicorn_hits)
    section("קשירות ל-:5000 (bind_5000)", bind5000_hits)
    section("קשירות ל-:8000 (bind_8000)", bind8000_hits)

    # אבחון וסיכום קצר
    print("\n==============================================")
    print(" אבחון מהיר:")
    print("==============================================")
    if not healthz_hits and not readyz_hits:
        print("• לא נמצאו נתיבי /healthz או /readyz — הוסף ראוט בריאות שמחזיר 200 מהר.")
    if app_run_hits:
        print("• נמצאו קריאות app.run — ודא שבענן אתה לא מפעיל אותן (Gunicorn צריך להרים את ה-app).")
    if port5000_kw and bind8000_hits:
        print("• יש ערבוב: קוד שמכריח 5000 לצד קשירה ל-8000 — אחֵד לפורט אחד (בענן $PORT=8000).")
    if bind5000_hits and bind8000_hits:
        print("• נמצאו גם קשירות 5000 וגם 8000 בקבצים — נקה כפילויות/סתירות.")
    if not gunicorn_hits:
        print("• לא זוהתה פקודת Gunicorn — ודא שבענן מרימים עם Gunicorn ולא עם app.run.")

    print("\nטיפ פעולה:")
    print("• מקומי: אפשר app.run עם PORT=5000.")
    print("• RunPod: תמיד Gunicorn על $PORT (לרוב 8000) + /healthz שמחזיר 200.")
    print("• חפש והסר port=5000 קשיח כאשר אתה מפרסם לענן.")

if __name__ == "__main__":
    main()
