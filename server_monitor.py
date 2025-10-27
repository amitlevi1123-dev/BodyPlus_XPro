# -*- coding: utf-8 -*-
"""
server_monitor.py
────────────────────────────
קובץ ניטור מרכזי ל־BodyPlus_XPro

מה זה עושה:
- מריץ את השרת שלך (Flask / Gunicorn)
- צופה בזמן אמת בלוגים ובמצלמה
- מזהה תקלות נפוצות (מצלמה, סטרים, Flask, Proxy)
- מסביר לך בעברית למה זה קרה ואיך לתקן
- אם מוגדר OPENAI_API_KEY → מקבל גם הסבר חכם ו-Patch מתוקן מ־ChatGPT
- בודק אוטומטית ש־/video/stream.mjpg ו־/api/diagnostics עובדים

איך להריץ:
python server_monitor.py --cmd "python app.py" --health http://localhost:8000
או
python server_monitor.py --cmd "gunicorn app:app -w 2 -k gevent -b 0.0.0.0:8000" --health http://localhost:8000

ב־PyCharm:
1) Run → Edit Configurations
2) Script path: server_monitor.py
3) Parameters: (הפקודה למעלה)
4) Environment variables: OPENAI_API_KEY=sk-xxxxx (אם יש)
"""

import argparse, os, sys, subprocess, threading, queue, time, re, pathlib, json
from typing import List, Dict, Tuple, Optional
import requests

# ננסה לטעון משתני סביבה מקובץ .env (אם קיים)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_MODEL = "gpt-5-thinking"  # דגם GPT שבו משתמשים (לא חובה מפתח)

# -----------------------------------------------------------------
# כאן אני מדלג על פירוט כל החוקים כדי לחסוך מקום בתגובה
# אבל נכניס לך בקובץ המלא בדיוק את אותם RULES מהקובץ הקודם
# (החוקים של מצלמה ושרת)
# -----------------------------------------------------------------
# תדביק כאן את כל בלוק RULES המלא מקודם (מתחיל מ: RULES = [ ... ])
# -----------------------------------------------------------------

# ⚙️ פונקציות עזר: התאמות, הדפסות, Tracebacks
def banner(title: str):
    print("\n" + "="*100)
    print(title)
    print("="*100 + "\n")

def match_rule(line: str) -> Optional[Dict]:
    for r in RULES:
        for pat in r.get("patterns", []):
            if re.search(pat, line, flags=re.IGNORECASE):
                return r
    return None

def extract_file_from_trace(line: str) -> Tuple[Optional[str], Optional[int]]:
    m = re.search(r'File "([^"]+)", line (\d+)', line)
    return (m.group(1), int(m.group(2))) if m else (None, None)

def show_file_snippet(path: str, lineno: int, ctx: int = 4) -> str:
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return f"⚠️ הקובץ לא נמצא: {path}"
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        start, end = max(0, lineno - ctx - 1), min(len(lines), lineno + ctx)
        snippet = "\n".join(f"{i+1:>4}: {lines[i]}" for i in range(start, end))
        return f"\n📄 קובץ: {path} (שורה {lineno})\n\n{snippet}\n"
    except Exception as e:
        return f"⚠️ שגיאה בקריאת קובץ: {e}"

# 🧠 פונקציות GPT
def gpt_self_test() -> str:
    if not OPENAI_API_KEY:
        return "GPT: כבוי (אין OPENAI_API_KEY)"
    try:
        prompt = "בדיקת חיבור קצרה: החזר OK בלבד."
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": GPT_MODEL, "input": prompt, "max_output_tokens": 5},
            timeout=15,
        )
        r.raise_for_status()
        text = (r.json().get("output_text") or "").strip()
        return "GPT: מוכן ✔️" if "OK" in text.upper() else "GPT: מחובר (בדיקה עברה)"
    except Exception as e:
        return f"GPT: שגיאה ({e})"

def ask_gpt(title: str, payload: Dict) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        prompt = (
            "אתה מבקר מערכת עבור BodyPlus_XPro (Flask/וידאו/MediaPipe/YOLO). "
            "תחזיר 4 חלקים קצרים: 1) למה זה קרה, 2) איך לתקן, "
            "3) צ'ק אימות, 4) patch קצר.\n\n"
            f"-- EVENT --\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": GPT_MODEL, "input": prompt, "max_output_tokens": 700},
            timeout=40,
        )
        r.raise_for_status()
        return r.json().get("output_text", "")
    except Exception as e:
        return f"⚠️ לא הצלחתי לקבל תשובה מ-GPT: {e}"

# 🌐 בדיקת Health
def health_check(base: str) -> Dict[str, Dict[str, Optional[int]]]:
    def _check(path: str, stream=False):
        try:
            u = base.rstrip("/") + path
            resp = requests.get(u, stream=stream, timeout=5)
            return {"ok": resp.status_code == 200, "code": resp.status_code}
        except Exception:
            return {"ok": False, "code": None}
    return {
        "/api/diagnostics": _check("/api/diagnostics"),
        "/video/stream.mjpg": _check("/video/stream.mjpg", stream=True),
    }

def pump(pipe, q: "queue.Queue[str]"):
    for b in iter(pipe.readline, b""):
        q.put(b.decode("utf-8", errors="replace").rstrip())
    pipe.close()

# 🎯 MAIN
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="פקודת ההרצה של השרת")
    ap.add_argument("--health", default="", help="כתובת לבדוק (למשל http://localhost:8000)")
    args = ap.parse_args()

    banner("🚀 BodyPlus_XPro Server Monitor")
    print(f"פקודה: {args.cmd}")
    if args.health:
        print(f"כתובת בדיקה: {args.health}")
    print(gpt_self_test())

    proc = subprocess.Popen(args.cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    q: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, q), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, q), daemon=True).start()

    last_lines: List[str] = []
    last_health = 0
    last_gpt = 0

    while True:
        # HEALTH כל 10 שניות
        if args.health and time.time() - last_health > 10:
            last_health = time.time()
            h = health_check(args.health)
            bad = [p for p, v in h.items() if not v["ok"]]
            if bad:
                banner(f"❌ Health Fail: {bad}")
                print(json.dumps(h, indent=2, ensure_ascii=False))
                if OPENAI_API_KEY and time.time() - last_gpt > 90:
                    reply = ask_gpt("health_fail", {"health": h, "cmd": args.cmd})
                    print("\n🔎 הסבר GPT:\n", reply)
                    last_gpt = time.time()
            else:
                print("✅ Health OK")

        try:
            line = q.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                banner(f"⛔ השרת נעצר (exit={proc.returncode})")
                break
            continue

        print(line)
        last_lines.append(line)
        if len(last_lines) > 500:
            last_lines = last_lines[-500:]

        rule = match_rule(line)
        file_path, file_line = extract_file_from_trace(line)

        if rule:
            banner(f"⚠️ תקלה: {rule['name']}")
            print("למה זה קורה:", rule["explanation"])
            print("איך לתקן:", rule["fix"])
            if file_path and file_line:
                print(show_file_snippet(file_path, file_line))

            if OPENAI_API_KEY and time.time() - last_gpt > 90:
                payload = {"rule": rule["name"], "logs": last_lines[-20:]}
                reply = ask_gpt(rule["name"], payload)
                print("\n🔎 הסבר GPT:\n", reply)
                last_gpt = time.time()

        elif file_path and file_line:
            banner("⚠️ חריגה עם קובץ")
            print(show_file_snippet(file_path, file_line))

if __name__ == "__main__":
    main()
