# -*- coding: utf-8 -*-
"""
server_monitor.py — ניטור + ביקורת AI ל־BodyPlus_XPro

יכולות עיקריות:
- מריץ שרת/פרוקסי לפי --cmd
- אוסף לוגים ל- --startup_window (ברירת מחדל: 30 שניות)
- בודק /video/stream.mjpg ו-/api/diagnostics (אם ניתנה --health)
- מזהה תקלות לפי RULES ומפיק ביקורת מסכמת למסך + דוח Markdown בתיקייה --report_dir
- אם ניתן --openai_api_key (או יש ב-.env/סביבה) → מבצע גם ביקורת AI ומציין זאת בלוגים
"""

from __future__ import annotations
import argparse, os, sys, subprocess, threading, queue, time, re, pathlib, json, datetime
from typing import List, Dict, Tuple, Optional
import requests

# ============ CLI ============
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help="פקודת ההרצה של השרת (למשל: python app/main.py)")
    ap.add_argument("--health", default="", help="כתובת בסיס לבדיקה (למשל http://127.0.0.1:8000)")
    ap.add_argument("--startup_window", type=int, default=30, help="משך חלון הבדיקה בשניות (ברירת מחדל: 30)")
    ap.add_argument("--report_dir", default="report", help="תיקיית הדוחות (ברירת מחדל: report)")
    ap.add_argument("--openai_api_key", default=None, help="מפתח OpenAI (עדיפות על .env/סביבה)")
    ap.add_argument("--verbose", action="store_true", help="פלט מפורט יותר לקונסול")
    return ap.parse_args()

# ============ ENV / .env ============
def resolve_api_key(cli_key: Optional[str]) -> str:
    # .env (אם קיים)
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
    except Exception:
        pass
    env_key = os.getenv("OPENAI_API_KEY", "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")
    return cli_key or env_key

# ============ RULES ============
RULES: List[Dict] = [
    dict(
        name="Address already in use (פורט תפוס)",
        patterns=[r"Address already in use", r"OSError: \[Errno (98|10048)\]", r"Only one usage of each socket address"],
        explanation="הפורט שעליו השרת מנסה להאזין כבר תפוס.",
        fix="סגור תהליך קודם או שנה פורט (8001/8002). ב-Windows: netstat -ano | findstr :8000 → taskkill /PID <pid> /F.",
        tags=["flask","proxy","port"],
    ),
    dict(
        name="Import/Module Not Found",
        patterns=[r"ModuleNotFoundError", r"ImportError: No module named", r"cannot import name"],
        explanation="חסר מודול או import לא תקין.",
        fix="pip install -r requirements.txt וודא PYTHONPATH תקין.",
        tags=["python","deps"],
    ),
    dict(
        name="RunPod Proxy Error",
        patterns=[r"\[proxy\]", r"RUNPOD_BASE", r"Bad Gateway", r"502", r"upstream.*runpod", r"invalid api key", r"401 Unauthorized"],
        explanation="שגיאה בפרוקסי RunPod (API/Upstream/הרשאות).",
        fix="בדוק RUNPOD_BASE, API key, מצב הפוד. אמת ‎/_proxy/health‎.",
        tags=["proxy","cloud"],
    ),
    dict(
        name="Camera in use / cannot open camera",
        patterns=[r"cannot open camera", r"Failed to open camera", r"VideoCapture\(.*\) failed", r"device busy"],
        explanation="מצלמה תפוסה/נעולה או חסומה.",
        fix="סגור ריצות מקבילות, העדף סטרים דרך דפדפן/FFmpeg במקום OpenCV מקומי.",
        tags=["video","camera"],
    ),
    dict(
        name="FFmpeg not found / path",
        patterns=[r"ffmpeg.*not found", r"FileNotFoundError.*ffmpeg", r"\[FFMPEG\].*not resolved"],
        explanation="FFmpeg לא נמצא/נתיב שגוי.",
        fix="התקן FFmpeg והוסף ל-PATH; אמת שהנתיב שמודפס בלוג תקין.",
        tags=["video","ffmpeg"],
    ),
    dict(
        name="MJPEG stream 404/500",
        patterns=[r"/video/stream\.mjpg.*(404|500)", r"GET /video/stream\.mjpg .* (404|500)"],
        explanation="ראוט הסטרים לא זמין/שגוי.",
        fix="ודא routes_video נטען, ושיש ייצור פריימים תקין בגנרטור MJPEG.",
        tags=["video","mjpeg","flask"],
    ),
    dict(
        name="Kinematics missing metrics",
        patterns=[r"missing_critical", r"pose\.available.*False", r"not_enough_frames", r"low_pose_confidence", r"no payload", r"PAYLOAD_VERSION mismatch"],
        explanation="חסרים מדדים לפוזה/קינמטיקה או איכות נמוכה.",
        fix="שפר תאורה/זווית, אמת שצנרת payload פעילה וגרסאות תואמות.",
        tags=["kinematics","payload"],
    ),
    dict(
        name="Object detection not running",
        patterns=[r"objdet\.(\w+)_present.*False", r"YOLO.*failed", r"onnxruntime.*error", r"model.*not found"],
        explanation="זיהוי אובייקטים לא רץ/מודל לא נטען.",
        fix="בדוק פרופיל דיטקטור, נתיבי מודלים, גרסת onnxruntime ולוג OD.",
        tags=["objdet","models"],
    ),
    dict(
        name="HTTP 500 / Exception",
        patterns=[r"500 Internal Server Error", r"Traceback \(most recent call last\):", r"Exception:"],
        explanation="חריגה בקוד השרת.",
        fix="בדוק Traceback (קובץ/שורה) ותקן None/KeyError/TypeError וכו׳.",
        tags=["flask","python"],
    ),
]

# ============ Utils ============
def log(msg: str, verbose=False):
    print(msg) if (verbose or True) else None

def banner(title: str):
    line = "=" * 88
    print(f"\n{line}\n{title}\n{line}\n")

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

# ============ GPT ============
def gpt_self_test(api_key: str) -> str:
    if not api_key:
        return "GPT: כבוי (אין OPENAI_API_KEY)"
    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-5-thinking", "input": "OK", "max_output_tokens": 5},
            timeout=15,
        )
        r.raise_for_status()
        txt = (r.json().get("output_text") or "").strip().upper()
        return "GPT: מוכן ✔️" if ("OK" in txt or txt) else "GPT: מחובר (בדיקה עברה)"
    except Exception as e:
        return f"GPT: שגיאה ({e})"

def ask_gpt(title: str, payload: Dict, api_key: str) -> Optional[str]:
    if not api_key:
        return None
    try:
        prompt = (
            "אתה מבקר מערכת עבור BodyPlus_XPro (Flask/וידאו/MediaPipe/YOLO). "
            "החזר 4 סעיפים קצרים: 1) למה זה קרה, 2) איך לתקן, 3) בדיקת אימות אחרי תיקון, 4) Patch/כיוון קוד קצר.\n\n"
            f"-- אירוע: {title} --\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "gpt-5-thinking", "input": prompt, "max_output_tokens": 700},
            timeout=40,
        )
        r.raise_for_status()
        return r.json().get("output_text", "")
    except Exception as e:
        return f"⚠️ לא הצלחתי לקבל תשובה מ-GPT: {e}"

# ============ Health ============
def health_check(base: str) -> Dict[str, Dict[str, Optional[int]]]:
    def _check(path: str, stream=False):
        try:
            u = base.rstrip("/") + path
            resp = requests.get(u, stream=stream, timeout=5)
            return {"ok": (resp.status_code == 200), "code": resp.status_code}
        except Exception:
            return {"ok": False, "code": None}
    return {
        "/api/diagnostics": _check("/api/diagnostics"),
        "/video/stream.mjpg": _check("/video/stream.mjpg", stream=True),
    }

# ============ Logs Pump ============
def pump(pipe, q: "queue.Queue[str]"):
    for b in iter(pipe.readline, b""):
        q.put(b.decode("utf-8", errors="replace").rstrip())
    pipe.close()

# ============ Report ============
def make_report_md(cmd: str, health_history: List[Dict[str, Dict[str, Optional[int]]]],
                   lines: List[str], matched_events: List[Dict],
                   output_dir: pathlib.Path, window_seconds: int, api_ok: bool, gpt_status: str) -> pathlib.Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    fpath = output_dir / f"דוח_ביקורת_AI_{ts}.md"

    last_health = health_history[-1] if health_history else {}

    pose_seen = any("pose.available" in l.lower() for l in lines)
    objdet_seen = any(re.search(r"objdet\.\w+_present.*(True|False)", l, re.I) for l in lines)
    stream_ok = (last_health.get("/video/stream.mjpg", {}) or {}).get("ok") is True

    md = []
    md.append(f"# 📋 דוח ביקורת AI — BodyPlus_XPro\n")
    md.append(f"- ⏱ חלון בדיקה: {window_seconds} שניות\n- 🧭 פקודה: `{cmd}`\n")
    md.append(f"- 🤖 סטטוס AI: {'יש API' if api_ok else 'אין API'} | {gpt_status}\n")
    md.append("## ✅ Health (מצב אחרון)")
    if last_health:
        for k, v in last_health.items():
            md.append(f"- `{k}` → ok={v.get('ok')} code={v.get('code')}")
    else:
        md.append("- אין נתוני Health (לא בוצעה בדיקה).")

    md.append("\n## 🎥 וידאו/קינמטיקה/זיהוי אובייקט — אינדיקציות")
    md.append(f"- pose.available זוהה בלוגים: {'כן' if pose_seen else 'לא'}")
    md.append(f"- objdet.*_present זוהה בלוגים: {'כן' if objdet_seen else 'לא'}")
    md.append(f"- /video/stream.mjpg: {'OK' if stream_ok else 'לא OK'}")

    if matched_events:
        md.append("\n## ⚠️ תקלות שאובחנו")
        for ev in matched_events:
            rule = ev['rule']
            md.append(f"### • {rule['name']}")
            md.append(f"**למה זה קורה:** {rule['explanation']}")
            md.append(f"**איך לתקן:** {rule['fix']}")
            if ev.get("file_path") and ev.get("file_line"):
                md.append(f"\n**מיקום בקוד:** `{ev['file_path']}` שורה {ev['file_line']}\n")
                if ev.get("snippet"):
                    md.append("```python")
                    md.append(ev["snippet"])
                    md.append("```")
            if ev.get("gpt"):
                md.append("\n**🧠 הסבר GPT:**")
                md.append(ev["gpt"])
            md.append("")
    else:
        md.append("\n## ✅ לא נמצאו תקלות קריטיות בחלון הבדיקה")

    md.append("\n## 🧾 קטע לוג אחרון (עד 60 שורות)")
    tail = lines[-60:] if len(lines) > 60 else lines
    md.append("```text")
    md.extend(tail)
    md.append("```")

    fpath.write_text("\n".join(md), encoding="utf-8")
    return fpath

# ============ Main ============
def main():
    args = parse_args()
    OPENAI_KEY = resolve_api_key(args.openai_api_key)
    api_ok = bool(OPENAI_KEY)

    banner("🚀 BodyPlus_XPro Server Monitor — התחלה")
    print(f"פקודה: {args.cmd}")
    print(f"תיקיית דוחות: {pathlib.Path(args.report_dir).resolve()}")
    print(f"בריאות (base): {args.health or 'לא הוגדר'}")
    print(f"API מצב: {'נמצא (CLI)' if args.openai_api_key else ('נמצא (.env/סביבה)' if api_ok else 'לא נמצא')}")
    gpt_status = gpt_self_test(OPENAI_KEY) if api_ok else "GPT: כבוי"
    print(gpt_status)

    # הרצת תהליך היעד
    proc = subprocess.Popen(args.cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    q: "queue.Queue[str]" = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, q), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, q), daemon=True).start()

    lines: List[str] = []
    matched_events: List[Dict] = []
    health_history: List[Dict] = []

    start = time.time()
    last_health_t = 0.0
    last_gpt = 0.0

    print(f"⏳ אוסף לוגים ל-{args.startup_window} שניות הראשונות...")

    while time.time() - start < args.startup_window:
        # Health כל 10 שנ׳
        if args.health and (time.time() - last_health_t) >= 10.0:
            last_health_t = time.time()
            h = health_check(args.health)
            health_history.append(h)
            bad = [p for p, v in h.items() if not v["ok"]]
            if bad:
                print(f"❌ Health Fail: {bad} → {h}")
                if api_ok and time.time() - last_gpt > 90:
                    reply = ask_gpt("health_fail", {"health": h, "cmd": args.cmd}, OPENAI_KEY)
                    if reply:
                        print("\n🔎 הסבר GPT:\n", reply)
                    last_gpt = time.time()
            else:
                print("✅ Health OK")

        try:
            line = q.get(timeout=0.2)
        except queue.Empty:
            if proc.poll() is not None:
                print(f"⛔ התהליך נעצר (exit={proc.returncode})")
                break
            continue

        print(line)
        lines.append(line)
        if len(lines) > 2000:
            lines = lines[-1000:]

        rule = match_rule(line)
        file_path, file_line = extract_file_from_trace(line)

        if rule:
            ev = {
                "rule": rule,
                "time": time.time() - start,
                "sample_line": line,
            }
            if file_path and file_line:
                ev["file_path"] = file_path
                ev["file_line"] = file_line
                ev["snippet"] = show_file_snippet(file_path, file_line)

            if api_ok and time.time() - last_gpt > 90:
                payload = {"rule": rule["name"], "logs_tail": lines[-30:]}
                reply = ask_gpt(rule["name"], payload, OPENAI_KEY)
                if reply:
                    ev["gpt"] = reply
                last_gpt = time.time()

            matched_events.append(ev)

    # יצירת התיקייה מראש כדי לוודא לוג ברור
    report_dir = pathlib.Path(args.report_dir)
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 תיקיית דוחות קיימת/נוצרה: {report_dir.resolve()}")
    except Exception as e:
        print(f"❌ כשל יצירת תיקיית דוחות: {e}")

    # דוח
    report_path = make_report_md(
        cmd=args.cmd,
        health_history=health_history,
        lines=lines,
        matched_events=matched_events,
        output_dir=report_dir,
        window_seconds=args.startup_window,
        api_ok=api_ok,
        gpt_status=gpt_status,
    )

    # ביקורת מסכמת למסך
    banner("🧾 ביקורת מסכמת (30 שניות ראשונות)")
    if health_history:
        last = health_history[-1]
        for k, v in last.items():
            print(f"- {k}: ok={v.get('ok')} code={v.get('code')}")
    else:
        print("- לא בוצעה בדיקת Health (לא הועברה --health).")

    issues = [ev['rule']['name'] for ev in matched_events]
    if issues:
        print("\n⚠️ תקלות שאובחנו:")
        for i, name in enumerate(issues, 1):
            print(f"  {i}. {name}")
    else:
        print("\n✅ לא נמצאו תקלות קריטיות בחלון הבדיקה.")

    print(f"\n📄 דוח נשמר: {report_path.resolve()}")
    print(f"🤖 סטטוס AI: {'פעיל' if api_ok else 'כבוי'} | {gpt_status}")

if __name__ == "__main__":
    main()
