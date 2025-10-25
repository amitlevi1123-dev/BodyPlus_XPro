# -*- coding: utf-8 -*-
"""
tools/diagnostics/phone_cam_integration_check.py
================================================
🇮🇱 בדיקת אינטגרציה לחיבור "מצלמת טלפון (IP)" לפרויקט BodyPlus_XPro

מטרה:
• לוודא שאין התנגשויות, שהקבצים הנכונים קיימים, ושיש API וכפתור שמגדירים מקור וידאו חיצוני (URL).
• לסמן מה חסר ולהדפיס Snippets מדויקים להדבקה (כולל שמות קבצים ומיקום לוגי).
• לשמור כל קובץ מתחת ל־700 שורות (אין נגיעה אוטומטית בקבצים — רק הנחיות).

איך מריצים:
    python tools/diagnostics/phone_cam_integration_check.py

מה נבדק:
1) קיום קבצים מרכזיים:
   - app/routes_video.py  (או ליפחות קובץ ראוטי וידאו)
   - templates/dashboard.html
2) קיום ראוט API: POST /api/video/source  שמקבל JSON {"url": "..."} ושומר מקור ל־video_source.txt
3) שימוש ב־cv2.VideoCapture(get_video_source()) במקום 0, ו־get_video_source() שקורא מ־video_source.txt
4) קיום /video/stream.mjpg (לצפייה) — או ראוט סטרים דומה
5) קיום כפתור בדשבורד עם קריאת fetch("/api/video/source", {method:"POST", ...})
6) תלויות: opencv-python-headless, Flask (ולא opencv עם GUI)

פלט:
• שורות PASS/FAIL/WARN עם הוראות "הדבק קוד כאן" כשצריך.
"""

from __future__ import annotations
import sys, re, json, os
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).parts[-3:] else Path.cwd()
APP_DIRS = [
    ROOT / "app",
    ROOT / "server",  # גיבוי אם פרויקט משתמש בשם אחר
]
TEMPLATES_DIRS = [
    ROOT / "templates",
    ROOT / "app" / "templates",
    ROOT / "admin_web" / "templates",
]
ROUTES_VIDEO_CANDIDATES = [
    ROOT / "app" / "routes_video.py",
    ROOT / "app" / "video" / "routes_video.py",
    ROOT / "server.py",  # לפעמים ראוטים חיים בקובץ שרת יחיד
]
DASHBOARD_CANDIDATES = [
    ROOT / "templates" / "dashboard.html",
    ROOT / "app" / "templates" / "dashboard.html",
    ROOT / "admin_web" / "templates" / "dashboard.html",
]

GREEN = "\033[92m"; RED = "\033[91m"; YELLOW = "\033[93m"; RESET = "\033[0m"
def ok(msg): print(f"{GREEN}PASS{RESET}  {msg}")
def fail(msg): print(f"{RED}FAIL{RESET}  {msg}")
def warn(msg): print(f"{YELLOW}WARN{RESET}  {msg}")

def read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None

def find_first_existing(paths) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None

def check_requirements():
    # בודק ש-opencv-headless מותקן, ולא חבילת GUI
    txt = read_text(ROOT / "requirements.txt") or ""
    headless = "opencv-python-headless" in txt
    opencv_gui = re.search(r"(?m)^\s*opencv-python\s*==?", txt) is not None
    if headless:
        ok("requirements.txt כולל opencv-python-headless (נכון לענן).")
    else:
        warn("מומלץ להשתמש ב-opencv-python-headless בענן. הוסף לשורה ב-requirements.txt.")

    if opencv_gui:
        warn("התגלתה תלות opencv-python (GUI). בענן עדיף להסיר/להחליף ל-headless כדי למנוע התנגשויות.")

    if "Flask" in txt:
        ok("requirements.txt כולל Flask.")
    else:
        fail("requirements.txt לא כולל Flask — הוסף Flask==3.0.3 (או גרסה תואמת).")

def check_routes_video() -> Tuple[Optional[Path], Optional[str]]:
    path = find_first_existing(ROUTES_VIDEO_CANDIDATES)
    if not path:
        fail("לא נמצא קובץ ראוטים לווידאו (חיפשתי app/routes_video.py, app/video/routes_video.py, server.py).")
        print("\n📎 הצעה: צור קובץ app/routes_video.py והדבק בו את הראוטים של וידאו (ראה קטעי קוד בהמשך).")
        return None, None
    ok(f"נמצא קובץ ראוטי וידאו: {path.relative_to(ROOT)}")
    src = read_text(path)
    if not src:
        fail("נכשל בקריאת קובץ הראוטים.")
        return path, None
    return path, src

def has_stream_route(src: str) -> bool:
    # בדיקה גסה ל-/video/stream.mjpg
    return bool(re.search(r'@app\.(get|route)\(\s*[\'"]\/video\/stream\.mjpg[\'"]', src))

def has_set_source_route(src: str) -> bool:
    # מחפש POST /api/video/source
    return bool(re.search(r'@app\.post\(\s*[\'"]\/api\/video\/source[\'"]\s*\)', src))

def has_get_video_source_func(src: str) -> bool:
    return "def get_video_source" in src

def uses_get_video_source_in_videocapture(src: str) -> bool:
    # חיפוש דפוס VideoCapture(...get_video_source()...) או קריאה לפונקציה
    pattern = r'cv2\.VideoCapture\(\s*get_video_source\(\)\s*\)'
    return bool(re.search(pattern, src))

def check_dashboard() -> Tuple[Optional[Path], Optional[str]]:
    path = find_first_existing(DASHBOARD_CANDIDATES)
    if not path:
        fail("לא נמצא templates/dashboard.html (חיפשתי ב-templates/, app/templates/, admin_web/templates/).")
        print("\n📎 הצעה: צור dashboard.html תחת התיקייה templates הרלוונטית לפרויקט.")
        return None, None
    ok(f"נמצא דשבורד: {path.relative_to(ROOT)}")
    src = read_text(path)
    if not src:
        fail("נכשל בקריאת dashboard.html")
        return path, None
    return path, src

def dashboard_has_button_and_fetch(src: str) -> bool:
    # בודק שיש כפתור עם id=btnPhoneCam וקריאת fetch ל-/api/video/source
    has_btn = 'id="btnPhoneCam"' in src or "btnPhoneCam" in src
    has_fetch = "/api/video/source" in src and "fetch(" in src
    return has_btn and has_fetch

def print_snippets():
    print("\n" + "="*72)
    print("📌 קטעי קוד מוכנים להדבקה (לשימוש אם חסר משהו)\n")

    print("1) פונקציית מקור וידאו + שימוש ב-VideoCapture(get_video_source())  — app/routes_video.py")
    print("-"*72)
    print(r'''
from pathlib import Path
import cv2

def get_video_source():
    """
    קורא את הכתובת האחרונה שנשמרה, או 0 כברירת מחדל.
    הערה: הקובץ video_source.txt נשמר בשורש הפרויקט (או לוגית ליד routes).
    """
    f = Path("video_source.txt")
    try:
        if f.exists():
            val = f.read_text(encoding="utf-8").strip()
            return val if val else 0
    except Exception:
        pass
    return 0

# דוגמה לשימוש:
# cap = cv2.VideoCapture(get_video_source())
''')

    print("\n2) ראוט API להגדרת מקור וידאו — app/routes_video.py")
    print("-"*72)
    print(r'''
from flask import request, jsonify
from pathlib import Path

@app.post("/api/video/source")
def set_video_source():
    """מקבל JSON {"url": "..."} ושומר מקור ל-video_source.txt"""
    data = request.get_json(silent=True) or {}
    source = (data.get("url") or "").strip()
    if not source:
        return jsonify({"ok": False, "error": "missing url"}), 400
    Path("video_source.txt").write_text(source, encoding="utf-8")
    return jsonify({"ok": True, "source": source})
''')

    print("\n3) וידוא קיום סטרים — app/routes_video.py  (/video/stream.mjpg)")
    print("-"*72)
    print(r'''
# דוגמת שלד ל-MJPEG (אם חסר אצלך). החלף בגנרטור הקיים שלך אם יש:
from flask import Response

def mjpeg_generator():
    # TODO: להחליף בזרימה האמיתית שלך שמדחפת פריימים מעובדים (yield b"--frame...")
    while False:
        yield b""

@app.get("/video/stream.mjpg")
def video_stream_mjpg():
    return Response(mjpeg_generator(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")
''')

    print("\n4) כפתור בדשבורד + fetch להגדרת מקור — templates/dashboard.html")
    print("-"*72)
    print(r'''
<button id="btnPhoneCam"
  class="px-4 py-2 bg-blue-500 text-white rounded-lg shadow hover:bg-blue-600">
  📱 הפעל מצלמת טלפון
</button>

<script>
document.getElementById("btnPhoneCam")?.addEventListener("click", async () => {
  const url = prompt("הדבק כתובת IP של הווידאו (לדוגמה http://192.168.1.23:8080/video):");
  if (!url) return;
  try {
    const res = await fetch("/api/video/source", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (data.ok) {
      alert("✅ הכתובת נשמרה. כבה והפעל מחדש את הווידאו/Camera.");
    } else {
      alert("❌ שגיאה: " + (data.error || "unknown"));
    }
  } catch (e) {
    alert("❌ שגיאת רשת: " + e);
  }
});
</script>
''')

def main():
    print(f"🔎 שורש פרויקט: {ROOT}")
    print("—"*60)

    # 0) דרישות סביבתיות
    check_requirements()
    print("—"*60)

    # 1) קובץ ראוטים לווידאו
    rv_path, rv_src = check_routes_video()
    if not rv_path or rv_src is None:
        print_snippets()
        sys.exit(1)

    # 1.א — /video/stream.mjpg
    if has_stream_route(rv_src):
        ok("נמצא ראוט /video/stream.mjpg (או דומה) — סטרים לצפייה קיים.")
    else:
        warn("לא נמצא ראוט /video/stream.mjpg — מומלץ להוסיף/לאשר שקיים גנרטור MJPEG.")

    # 1.ב — POST /api/video/source
    if has_set_source_route(rv_src):
        ok("נמצא ראוט POST /api/video/source — הגדרת מקור וידאו חיצוני.")
    else:
        fail("אין POST /api/video/source — הוסף את הראוט כדי לעדכן מקור וידאו חיצוני (טלפון).")

    # 1.ג — פונקציה get_video_source()
    if has_get_video_source_func(rv_src):
        ok("נמצאה פונקציה get_video_source().")
    else:
        fail("אין get_video_source() — הוסף פונקציה שקוראת מ-video_source.txt ומחזירה 0 כברירת מחדל.")

    # 1.ד — שימוש בפועל ב-VideoCapture(get_video_source())
    if uses_get_video_source_in_videocapture(rv_src):
        ok("נמצא שימוש ב-cv2.VideoCapture(get_video_source()) — טוב, המקור דינמי.")
    else:
        warn("לא זוהה שימוש ב-VideoCapture(get_video_source()). ודא שאינך נשאר על 0/קובץ קבוע.")

    print("—"*60)

    # 2) דשבורד וכפתור
    db_path, db_src = check_dashboard()
    if not db_path or db_src is None:
        print_snippets()
        sys.exit(1)

    if dashboard_has_button_and_fetch(db_src):
        ok("בדשבורד קיים כפתור + fetch ל-/api/video/source (id=btnPhoneCam).")
    else:
        fail("אין כפתור/JS בדשבורד להגדרת מקור. הוסף את ה-Snippet לכפתור + fetch (ראה קטע 4).")

    print("—"*60)

    # 3) סיכום פעולות (רשימת TODO תמציתית)
    todos = []
    if not has_stream_route(rv_src):
        todos.append("הוסף /video/stream.mjpg או אשר שהסטרים קיים ופועל.")
    if not has_set_source_route(rv_src):
        todos.append("הוסף POST /api/video/source (שומר ל-video_source.txt).")
    if not has_get_video_source_func(rv_src):
        todos.append("הוסף get_video_source() שקורא מ-video_source.txt.")
    if not uses_get_video_source_in_videocapture(rv_src):
        todos.append("עדכן פתיחת מצלמה ל-cv2.VideoCapture(get_video_source()).")
    if not dashboard_has_button_and_fetch(db_src):
        todos.append("הוסף בדשבורד כפתור + fetch ל-/api/video/source (id=btnPhoneCam).")

    if not todos:
        ok("כל בדיקות האינטגרציה עברו. אתה מוכן לחיבור מצלמת טלפון (IP). 🎉")
    else:
        print(f"{YELLOW}TODO (לפי סדר עדיפות):{RESET}")
        for i, t in enumerate(todos, 1):
            print(f" {i}. {t}")

    # 4) טיפים מהירים
    print("\n💡 טיפים:")
    print("• לשימוש בענן: שמור opencv-python-headless ב-requirements, והימנע מ-opencv עם GUI.")
    print("• כתובת טלפון מקומית (192.168.x.x) לא תעבוד מענן — השתמש ב-ngrok/טאנל לכתובת ציבורית.")
    print("• תשמור קבצים מתחת ל-700 שורות ובתחילת כל קובץ כותרת הסברית קצרה בעברית.")

if __name__ == "__main__":
    main()
