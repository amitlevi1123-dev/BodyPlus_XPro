# -*- coding: utf-8 -*-
"""
tools/monitor_run.py
מריץ את השרת שלך, מנטר STDOUT/STDERR, בודק Health (/video/stream.mjpg, /api/diagnostics),
מזהה תקלות נפוצות במצלמה/וידאו ובשרת/Flask/Proxy, ומציג:
- כותרת התקלה
- למה זה קורה (הסבר קצר)
- איך לתקן (צעדים ברורים)
- אם יש traceback: קובץ+שורה + קטע קוד סביב הבעיה
(אופציונלי) אם יש OPENAI_API_KEY - יבקש גם הסבר/טלאי קצר מ-GPT.

שימוש לדוגמה:
python tools/monitor_run.py --cmd "python app.py" --health http://localhost:8000
או:
python tools/monitor_run.py --cmd "gunicorn app:app -w 2 -k gevent -b 0.0.0.0:8000" --health http://localhost:8000
"""

import argparse, os, sys, subprocess, threading, queue, time, re, pathlib, json
from typing import List, Dict, Tuple, Optional
import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_MODEL = "gpt-5-thinking"  # אופציונלי; אם אין מפתח - לא נשלח

# -----------------------------
# חבילת חוקים (מובנית בקובץ)
# -----------------------------
RULES: List[Dict] = [
    # --- מצלמה / וידאו ---
    {
        "name": "Camera device busy / cannot open camera",
        "severity": "error",
        "patterns": [r"could not open camera", r"VideoCapture.*isOpened.*False", r"device busy", r"Resource temporarily unavailable"],
        "explanation": "המצלמה תפוסה/לא נגישה (תהליך אחר פתוח, אינדקס שגוי, או הרשאות חסרות).",
        "fix": "סגור אפליקציות מצלמה/טאבים עם וידאו; נסה index אחר (0/1/2) או RTSP/HTTP נכון; בלינוקס ודא הרשאות ל-/dev/video* (קבוצת video).",
    },
    {
        "name": "Wrong camera index / missing device",
        "severity": "warn",
        "patterns": [r"No such device", r"VIDIOC_.* failed", r"cannot identify device"],
        "explanation": "האינדקס לא תואם להתקן או שההתקן לא מזוהה במערכת.",
        "fix": "אתר אינדקס תקין (Linux: v4l2-ctl --list-devices) ועדכן בקוד/ENV.",
    },
    {
        "name": "Frame read failed (frame is None / ret==False)",
        "severity": "warn",
        "patterns": [r"frame is None", r"ret == False", r"Failed to read frame", r"Empty frame"],
        "explanation": "קריאת פריים נכשלה (ניתוק רגעי/חושך/latency). בלי טיפול – הלולאה נתקעת.",
        "fix": "הוסף בדיקת None + reconnect; הורד רזולוציה/קצב דגימה; ודא תאורה בסיסית.",
    },
    {
        "name": "RTSP/Network camera auth/url",
        "severity": "error",
        "patterns": [r"401 Unauthorized", r"403 Forbidden", r"Connection refused", r"RST_STREAM", r"getaddrinfo failed"],
        "explanation": "מצלמת רשת/RTSP: כתובת/יוזר/סיסמה/פורט לא נכונים או לא נגישים.",
        "fix": "אמת URL מלא כולל יוזר/סיסמה ופורט; בדוק שפורט פתוח ב-Firewall/RunPod; נסה ping/traceroute.",
    },
    {
        "name": "Unsupported pixel format / backend",
        "severity": "warn",
        "patterns": [r"Unsupported format", r"GStreamer warning", r"Could not find codec parameters", r"CAP_FFMPEG:"],
        "explanation": "פורמט/קודק לא נתמך ע\"י backend הנוכחי (FFmpeg/GStreamer).",
        "fix": "התקן FFmpeg/GStreamer; כוון backend מתאים; נרמל ל-BGR/RGB והפחת רזולוציה.",
    },
    {
        "name": "USB bandwidth / power saving",
        "severity": "warn",
        "patterns": [r"Not enough bandwidth", r"USB.*reset", r"Device disconnected and reconnected"],
        "explanation": "עומס USB/חיסכון חשמל מפסיק מצלמה אקראית.",
        "fix": "חבר ליציאה אחרת/ישירה; כבה USB power saving; הורד FPS/רזולוציה.",
    },
    {
        "name": "FPS drop / pipeline too slow",
        "severity": "warn",
        "patterns": [r"Processing time too high", r"FPS < ?\d+", r"buffer overflow", r"queue full"],
        "explanation": "עיבוד איטי (מודל כבד/ציור overlay) → צניחת FPS וזמן תגובה.",
        "fix": "דגם קל (MoveNet Lightning/YOLO-N), דגום כל N פריימים, כבה ציור Debug, נהל תורים נכון.",
    },
    {
        "name": "GPU/CUDA out of memory",
        "severity": "error",
        "patterns": [r"CUDA out of memory", r"c10::Error.*CUDA", r"cuMemAlloc failed"],
        "explanation": "נגמר זיכרון GPU באינפרנס.",
        "fix": "הקטן רזולוציה, עבור לדגם קטן, נקה טנזורים (torch.cuda.empty_cache()), batch=1.",
    },
    {
        "name": "Color conversion / shape mismatch",
        "severity": "warn",
        "patterns": [r"\(-215:Assertion failed\)", r"invalid shape", r"channels != 3", r"cv::cvtColor"],
        "explanation": "ציפית ל-BGR/RGB בגודל מסוים וקיבלת פורמט/מימדים אחרים.",
        "fix": "ודא המרה אחידה ל-BGR/RGB; הדפס shape לפני שליחה למודל; התאם רזולוציה.",
    },
    {
        "name": "Resource leak (VideoCapture not released)",
        "severity": "warn",
        "patterns": [r"Too many open files", r"cannot allocate memory", r"Video device busy after stop"],
        "explanation": "לא קוראים release()/destroy → דליפת משאבים; לאחר כמה הפעלות המצלמה ‘תיתקע’.",
        "fix": "עטוף ב-try/finally; cap.release() ו-cv2.destroyAllWindows().",
    },

    # --- שרת / Flask / Proxy / ניהול ---
    {
        "name": "Port already in use / bind error",
        "severity": "error",
        "patterns": [r"Address already in use", r"OSError: \[Errno 98\]", r"bind\(\) failed", r"Only one usage of each socket address"],
        "explanation": "הפורט תפוס ע\"י תהליך אחר או שהשרת מאזין לכתובת לא נכונה.",
        "fix": "עצור תהליך קודם (lsof -i :PORT / netstat), או החלף פורט. לפריסה ציבורית האזן על 0.0.0.0.",
    },
    {
        "name": "Localhost-only (not reachable from outside)",
        "severity": "warn",
        "patterns": [r"Running on http://127\.0\.0\.1", r"Running on http://localhost"],
        "explanation": "השרת מקשיב רק ל-localhost; מבחוץ לא יראו את האתר ללא proxy.",
        "fix": "הרץ עם host=0.0.0.0 (Flask) או gunicorn -b 0.0.0.0:PORT; ודא שה-proxy מפנה נכון.",
    },
    {
        "name": "Stream endpoint missing / 404",
        "severity": "error",
        "patterns": [r"404 NOT FOUND", r"BuildError", r"Not Found: /video/stream\.mjpg"],
        "explanation": "הנתיב /video/stream.mjpg חסר/שונה; ה-Frontend לא יראה וידאו.",
        "fix": "הוסף route שמחזיר MJPEG עם mimetype נכון; ודא proxy→host/port/נתיב.",
    },
    {
        "name": "Wrong mimetype / MJPEG headers",
        "severity": "warn",
        "patterns": [r"Content-Type.*text/html", r"multipart/x-mixed-replace boundary missing"],
        "explanation": "סטרים MJPEG חייב header: multipart/x-mixed-replace; אחרת דפדפן לא יציג רצף פריימים.",
        "fix": "Response(generator, mimetype='multipart/x-mixed-replace; boundary=frame') ו-boundary בכל פריים.",
    },
    {
        "name": "Debug/auto-reload in production",
        "severity": "warn",
        "patterns": [r"Debugger is active!", r"Detected change in '", r"FLASK_DEBUG=1"],
        "explanation": "מצב דיבוג גורם לריסטים/לטנטיות; לא לפרודקשן.",
        "fix": "פרוס עם gunicorn/uWSGI; כבה auto-reload; השאר debug רק לפיתוח.",
    },
    {
        "name": "Gunicorn worker/class mismatch",
        "severity": "warn",
        "patterns": [r"Worker failed to boot", r"No event loop", r"gevent not installed"],
        "explanation": "מחלקת worker לא תואמת (gevent/eventlet) או תלות חסרה; סטרים עשוי להתקע.",
        "fix": "התקן gevent או השתמש sync workers; ודא -k מתאים לסטרים.",
    },
    {
        "name": "Reverse proxy misconfig / bad gateway",
        "severity": "error",
        "patterns": [r"502 Bad Gateway", r"504 Gateway Timeout", r"upstream prematurely closed connection"],
        "explanation": "ה-proxy לא מצליח להגיע לשרת (HOST/PORT שגוי, timeout קצר).",
        "fix": "אמת target (HOST:PORT), הגדל timeouts, ודא שהשרת מאזין ו-Firewall פתוח.",
    },
    {
        "name": "CORS / Mixed content issues",
        "severity": "warn",
        "patterns": [r"CORS policy", r"Mixed Content", r"No 'Access-Control-Allow-Origin' header"],
        "explanation": "הדפדפן חוסם בקשות בגלל דומיין/פרוטוקול שונים.",
        "fix": "אפשר CORS (Flask-CORS/כותרות), השתמש ב-HTTPS לכול; אל תגיש HTTP בתוך דף HTTPS.",
    },
    {
        "name": "Long-running generator timeout",
        "severity": "warn",
        "patterns": [r"write EPIPE", r"client disconnected", r"BrokenPipeError", r"Timeout writing to client"],
        "explanation": "לקוח נסגר/Proxy ניתק בזמן סטרים; הגנרטור ממשיך לכתוב ונופל.",
        "fix": "תפוס BrokenPipe וסגור generator; קבע timeouts/heartbeats ב-proxy.",
    },
    {
        "name": "Static files / template not found",
        "severity": "warn",
        "patterns": [r"TemplateNotFound", r"GET /static/.* 404"],
        "explanation": "תבנית/קובץ סטטי חסר – עמוד ניהול לא ייטען.",
        "fix": "ודא TEMPLATE_FOLDER/STATIC_FOLDER ונתיבים יחסיים נכונים; הקבצים קיימים בקונטיינר.",
    },
    {
        "name": "ENV missing / config error",
        "severity": "error",
        "patterns": [r"KeyError: '", r"Environment variable", r"config.*missing"],
        "explanation": "משתנה סביבה/קונפיג חובה חסר → קריסה/התנהגות שגויה.",
        "fix": "הגדר ערכי ברירת מחדל; השתמש os.environ.get; מנע יציאה קשה ללא הודעת שגיאה ברורה.",
    },
    {
        "name": "DB connection/refused/timeout",
        "severity": "error",
        "patterns": [r"psycopg2.*could not connect", r"SQL.*timeout", r"Connection refused.*5432"],
        "explanation": "חיבור DB נפל; דוחות/שמירות ייכשלו.",
        "fix": "אמת URI/סיסמה/פורט; הוסף retry/backoff; תמוך ב-offline queue.",
    },
    {
        "name": "Auth/session for Admin",
        "severity": "warn",
        "patterns": [r"werkzeug.exceptions.Unauthorized", r"CSRF token missing", r"Login required"],
        "explanation": "עמוד ניהול דורש הזדהות/CSRF; בלעדיהם נחסם.",
        "fix": "ודא session/key, מסך כניסה, או בטל CSRF למסלולי GET/צפייה.",
    },
]

# -----------------------------
# עזר: הדפסה יפה, התאמת חוקים, חיתוך Traceback
# -----------------------------
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
    if not m:
        return None, None
    return m.group(1), int(m.group(2))

def show_file_snippet(path: str, lineno: int, ctx: int = 4) -> str:
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return f"⚠️ הקובץ לא נמצא: {path}"
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        start = max(0, lineno - ctx - 1)
        end = min(len(lines), lineno + ctx)
        snippet = "\n".join(f"{i+1:>4}: {lines[i]}" for i in range(start, end))
        return f"\n📄 קובץ: {path} (שורה {lineno})\n\n{snippet}\n"
    except Exception as e:
        return f"⚠️ שגיאה בקריאת קובץ: {e}"

def ask_gpt(title: str, payload: Dict, last_lines: List[str]) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    try:
        prompt = (
            "אתה מבקר מערכת עבור BodyPlus_XPro (Flask/וידאו/MediaPipe/YOLO). "
            "תחזיר 4 חלקים קצרים: "
            "1) למה זה קרה, 2) איך לתקן (צעדים + patch קצר), "
            "3) צ'ק אימות אחרי התיקון (3 נק'), 4) אם יש קובץ/שורה: השינוי המדויק.\n\n"
            f"-- EVENT JSON --\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "לשמור על הנתיב /video/stream.mjpg ועל FPS>=20."
        )
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={"model": GPT_MODEL, "input": prompt, "temperature": 0.2, "max_output_tokens": 900},
            timeout=45,
        )
        r.raise_for_status()
        j = r.json()
        return j.get("output_text") or (j.get("choices", [{}])[0].get("text"))
    except Exception as e:
        return f"⚠️ לא הצלחתי לקבל הסבר מ-GPT: {e}"

def health_check(base_url: str) -> Dict[str, Dict[str, Optional[int]]]:
    def _get(path: str, stream=False, timeout=5):
        try:
            u = base_url.rstrip("/") + path
            resp = requests.get(u, stream=stream, timeout=timeout)
            return {"ok": (resp.status_code == 200), "code": resp.status_code}
        except Exception:
            return {"ok": False, "code": None}
    return {
        "/api/diagnostics": _get("/api/diagnostics"),
        "/video/stream.mjpg": _get("/video/stream.mjpg", stream=True),
    }

def pump(pipe, tag: str, q: "queue.Queue[Tuple[str,str]]"):
    for b in iter(pipe.readline, b""):
        q.put((tag, b.decode("utf-8", errors="replace").rstrip("\n")))
    pipe.close()

# -----------------------------
# main
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cmd", required=True, help='פקודת ההרצה של השרת (למשל: "python app.py")')
    ap.add_argument("--health", default="", help="Base URL לבדיקות (למשל http://localhost:8000 או URL ציבורי של RunPod)")
    ap.add_argument("--cooldown", type=int, default=90, help="מרווח שניות בין שליחות GPT מאותו סוג")
    ap.add_argument("--no-gpt", action="store_true", help="אל תשלח ל-GPT גם אם OPENAI_API_KEY מוגדר")
    args = ap.parse_args()

    banner("🚀 מפעיל שרת עם ניטור חכם")
    print(f"פקודה: {args.cmd}")
    if args.health:
        print(f"Health URL: {args.health}")
    print("מצב GPT:", "פעיל" if (OPENAI_API_KEY and not args.no_gpt) else "כבוי")

    proc = subprocess.Popen(args.cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    q: "queue.Queue[Tuple[str,str]]" = queue.Queue()
    threading.Thread(target=pump, args=(proc.stdout, "OUT", q), daemon=True).start()
    threading.Thread(target=pump, args=(proc.stderr, "ERR", q), daemon=True).start()

    last_lines: List[str] = []
    last_health_ts = 0.0
    last_gpt_ts = 0.0
    last_event_type = ""

    try:
        while True:
            # HEALTH
            now = time.time()
            if args.health and (now - last_health_ts > 10):
                last_health_ts = now
                h = health_check(args.health)
                bad = [k for k, v in h.items() if not v["ok"]]
                if bad:
                    for path in bad:
                        code = h[path]["code"]
                        banner(f"❌ HEALTH FAIL: {path} code={code}")
                        print("למה זה קריטי: ה-Endpoint לא מחזיר 200 → הלקוח/טלפון לא יראה וידאו/דשבורד.")
                        print("מה לבדוק עכשיו:")
                        print("- האם השרת מאזין על 0.0.0.0 ובפורט הנכון?")
                        print("- האם הנתיב קיים בפלאסק/ה-proxy מפנה נכון?")
                        print("- יש חריגה בלוג (מטה) שקשורה לזה?")
                    # GPT payload
                    if OPENAI_API_KEY and not args.no-gpt and (now - last_gpt_ts > args.cooldown):
                        payload = {
                            "project": "BodyPlus_XPro",
                            "runtime": {"url_base": args.health, "server_cmd": args.cmd},
                            "event": {"type": "health_fail", "timestamp": time.time()},
                            "health": h,
                            "logs_tail": last_lines[-40:],
                            "constraints": {"must_keep_routes": ["/video/stream.mjpg"], "perf_targets": {"fps_min": 20}},
                        }
                        reply = ask_gpt("health_fail", payload, last_lines)
                        if reply:
                            print("\n🔎 הסבר GPT:\n" + reply)
                            last_gpt_ts = now
                            last_event_type = "health_fail"
                else:
                    print("✅ Health OK: /api/diagnostics, /video/stream.mjpg")

            # LOGS
            try:
                tag, line = q.get(timeout=0.2)
            except queue.Empty:
                # תהליך נגמר?
                if proc.poll() is not None:
                    banner(f"⛔ השרת נעצר (exit={proc.returncode})")
                    break
                continue

            print(line)
            last_lines.append(line)
            if len(last_lines) > 500:
                last_lines = last_lines[-500:]

            # התאמת חוקים
            rule = match_rule(line)
            file_path, file_line = extract_file_from_trace(line)

            if rule:
                banner(f"⚠️ זוהתה בעיה: {rule['name']}  (severity: {rule.get('severity','warn')})")
                print("למה זה קורה:\n" + rule.get("explanation", ""))
                print("\nאיך לתקן עכשיו:\n" + rule.get("fix", ""))

                if file_path and file_line:
                    print(show_file_snippet(file_path, file_line))

                # GPT (עם cooldown)
                if OPENAI_API_KEY and not args.no_gpt and (time.time() - last_gpt_ts > args.cooldown):
                    payload = {
                        "project": "BodyPlus_XPro",
                        "runtime": {"url_base": args.health, "server_cmd": args.cmd},
                        "event": {"type": "rule_match", "rule_name": rule["name"], "timestamp": time.time()},
                        "health": {},  # לא חובה כאן
                        "logs_tail": last_lines[-40:],
                        "file_context": {
                            "path": file_path, "lineno": file_line,
                            "snippet_head_tail": show_file_snippet(file_path, file_line) if (file_path and file_line) else None
                        },
                        "constraints": {"must_keep_routes": ["/video/stream.mjpg"], "perf_targets": {"fps_min": 20}},
                    }
                    reply = ask_gpt(rule["name"], payload, last_lines)
                    if reply:
                        print("\n🔎 הסבר GPT:\n" + reply)
                        last_gpt_ts = time.time()
                        last_event_type = "rule_match"

            # Traceback בלי חוק (נרצה עדיין קובץ+שורה)
            elif file_path and file_line:
                banner("⚠️ זוהתה חריגה עם קובץ/שורה")
                print(show_file_snippet(file_path, file_line))

                if OPENAI_API_KEY and not args.no_gpt and (time.time() - last_gpt_ts > args.cooldown):
                    payload = {
                        "project": "BodyPlus_XPro",
                        "runtime": {"url_base": args.health, "server_cmd": args.cmd},
                        "event": {"type": "traceback", "timestamp": time.time()},
                        "logs_tail": last_lines[-40:],
                        "file_context": {
                            "path": file_path, "lineno": file_line,
                            "snippet_head_tail": show_file_snippet(file_path, file_line)
                        },
                        "constraints": {"must_keep_routes": ["/video/stream.mjpg"], "perf_targets": {"fps_min": 20}},
                    }
                    reply = ask_gpt("traceback", payload, last_lines)
                    if reply:
                        print("\n🔎 הסבר GPT:\n" + reply)
                        last_gpt_ts = time.time()
                        last_event_type = "traceback"

    except KeyboardInterrupt:
        print("\n🛑 עצירה ידנית…")
        try:
            proc.terminate()
        except Exception:
            pass

if __name__ == "__main__":
    main()
