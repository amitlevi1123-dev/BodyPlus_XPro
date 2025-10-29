# -*- coding: utf-8 -*-
# =============================================================================
# 🔍 check_pipeline.py — דיאגנוסטיקה מלאה לזרימת הווידאו והמדידות (ללא OpenCV)
# -----------------------------------------------------------------------------
# מה הקובץ בודק?
# 1) שרת Flask חי? (/health, /api/video/status)
# 2) ingest עובד? (POST /api/ingest_frame עם JPEG מינימלי)
# 3) יש payload? (בדיקה חוזרת של /api/payload_last או /payload)
# 4) MediaPipe מותקן? אפשר לפתוח Pose/Hands?
# 5) מודול KINEMATICS קיים? פונקציות בסיסיות זמינות?
# 6) admin_web.state פעיל? (get_payload/is_frame_ready)
# 7) Object Detection אם קיים — סטטוס בסיסי (/api/video/status ו/או admin_web.state.get_od_snapshot)
#
# פלט:
# • מסך: טבלת PASS/FAIL + "סיבה אפשרית" + "מה עושים"
# • קובץ דוח: report/diagnostics_<timestamp>.md (נוצר אוטומטית)
#
# הרצה (לוקאלי, ברירת מחדל ל- http://127.0.0.1:5000):
#   python tools/diagnostics/check_pipeline.py
# או עם בסיס אחר:
#   python tools/diagnostics/check_pipeline.py --base http://127.0.0.1:8080
# אפשר להזריק פריים מבחוץ:
#   python tools/diagnostics/check_pipeline.py --frame C:\path\to\frame.jpg
# =============================================================================

from __future__ import annotations
import os, sys, time, json, argparse, textwrap, datetime, traceback
from typing import Optional, Dict, Any, Tuple
from io import BytesIO

# ----- Mini JPEG (למקרה שאין קובץ) -----
_MINI_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00"
    b"\xff\xdb\x00C\x00" + b"\x08"*64 +
    b"\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01\"\x00\x02\x11\x01\x03\x11\x01"
    b"\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11\x00?\x00\xcf\xff\xd9"
)

# ----- תלותים רכים -----
try:
    import requests
except Exception:
    print("❌ חסר 'requests'. התקן:  pip install requests")
    sys.exit(1)

try:
    from PIL import Image  # type: ignore
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

# ===== Utilities =====
def ts() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_json(obj: Any) -> str:
    try: return json.dumps(obj, ensure_ascii=False)
    except Exception: return "<unserializable>"

def read_file_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            b = f.read()
        return b
    except Exception:
        return None

def fmt_row(label: str, ok: bool, detail: str = "", fix: str = "") -> str:
    status = "PASS" if ok else "FAIL"
    return f"| {label} | {status} | {detail} | {fix} |"

def ensure_report_dir() -> str:
    base = os.path.join(os.getcwd(), "report")
    try: os.makedirs(base, exist_ok=True)
    except Exception: pass
    return base

def detect_payload_endpoint(base: str) -> str:
    # מנסה /api/payload_last ואז /payload
    for p in ("/api/payload_last", "/payload"):
        try:
            r = requests.get(base.rstrip("/") + p, timeout=1.5)
            if r.status_code == 200:
                return p
        except Exception:
            pass
    return "/api/payload_last"  # נשתמש כברירת מחדל

# ===== Checks =====
def check_server_health(base: str) -> Tuple[bool, str, str]:
    try:
        r = requests.get(base.rstrip("/") + "/health", timeout=1.5)
        if r.status_code == 200:
            return True, "שרת חי", "אין פעולה"
        return False, f"סטטוס={r.status_code}", "בדוק שה־main רץ ושפורט נכון"
    except Exception as e:
        return False, f"שגיאת חיבור: {e}", "בדוק שהשרת רץ (Gunicorn/Flask), כתובת/פורט נכונים, Firewall"

def check_video_status(base: str) -> Tuple[bool, Dict[str, Any], str, str]:
    try:
        r = requests.get(base.rstrip("/") + "/api/video/status", timeout=1.5)
        if r.status_code != 200:
            return False, {}, f"סטטוס={r.status_code}", "בדוק רישום ה-Blueprint של routes_video"
        data = r.json()
        ok = bool(data.get("ok", False))
        if not ok:
            return False, data, "status ok=false", "פתח לוגים של השרת ובדוק חריגות ב-video/status"
        return True, data, "אחזרת סטטוס הצליחה", "אין פעולה"
    except Exception as e:
        return False, {}, f"שגיאת חיבור: {e}", "בדוק שהשרת רץ ונתיב /api/video/status רשום"

def push_ingest_frame(base: str, frame_bytes: Optional[bytes]) -> Tuple[bool, str, str]:
    try:
        payload = frame_bytes or _MINI_JPEG
        # שולחים raw JPEG (גם multipart אפשרי, אבל raw פשוט יותר)
        r = requests.post(base.rstrip("/") + "/api/ingest_frame",
                          data=payload, headers={"Content-Type": "image/jpeg"},
                          timeout=2.0)
        if r.status_code == 200 and (r.json().get("ok") is True):
            return True, "ingest OK", "אין פעולה"
        return False, f"ingest כשל (status={r.status_code}, body={r.text[:200]})", "בדוק את ה־route /api/ingest_frame ואת get_streamer()"
    except Exception as e:
        return False, f"שגיאה בשליחת ingest: {e}", "בדוק חיבור מקומי/Proxy/אבטחה ושה-Blueprint נטען"

def wait_for_payload(base: str, endpoint: str, timeout_sec: float = 4.0) -> Tuple[bool, Dict[str, Any], str, str]:
    t0 = time.time()
    last_err = ""
    url = base.rstrip("/") + endpoint
    while (time.time() - t0) < timeout_sec:
        try:
            r = requests.get(url, timeout=1.5)
            if r.status_code == 200:
                data = r.json() if "application/json" in (r.headers.get("Content-Type","")) else {}
                # תנאי מינימלי: יש ts_ms או metrics או mp/objdet
                if isinstance(data, dict) and (data.get("ts_ms") or data.get("metrics") or data.get("mp") or data.get("objdet")):
                    return True, data, "payload התקבל", "אין פעולה"
                last_err = "payload ריק/חסר"
            else:
                last_err = f"סטטוס={r.status_code}"
        except Exception as e:
            last_err = f"שגיאה בקריאה: {e}"
        time.sleep(0.25)
    return False, {}, last_err or "לא התקבל payload בזמן", "ודא שה־main מריץ לולאה שמביאה frame→MediaPipe→KINEMATICS→set_payload"

def check_mediapipe_local() -> Tuple[bool, str, str, Dict[str, Any]]:
    info = {}
    try:
        import mediapipe as mp  # type: ignore
        info["mediapipe_version"] = getattr(mp, "__version__", "unknown")
        # בדיקה קלה לפתיחה
        pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=0)
        hands = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2)
        pose.close(); hands.close()
        return True, f"MediaPipe מותקן ({info['mediapipe_version']})", "אין פעולה", info
    except Exception as e:
        return False, f"mediapipe לא נטען/לא נפתח: {e}", "pip install mediapipe; בדוק תאימות Python/CPU/GPU", info

def check_kinematics_local() -> Tuple[bool, str, str]:
    try:
        sys.path.insert(0, os.getcwd())
        from core.kinematics import KINEMATICS  # type: ignore
        # בדיקה מינימלית: קיימת פונקציה compute או אובייקט עם compute
        ok = hasattr(KINEMATICS, "compute") or callable(getattr(KINEMATICS, "compute", None))
        if not ok:
            return False, "אין compute ב-KINEMATICS", "בדוק core/kinematics.py"
        return True, "KINEMATICS נטען", "אין פעולה"
    except Exception as e:
        return False, f"ייבוא KINEMATICS נכשל: {e}", "ודא מסלול פרויקט נכון, קובץ core/kinematics.py קיים ותקין"

def check_state_bridge_local() -> Tuple[bool, str, str]:
    try:
        sys.path.insert(0, os.getcwd())
        from admin_web.state import get_payload, is_frame_ready  # type: ignore
        _ = callable(get_payload) and callable(is_frame_ready)
        return True, "admin_web.state זמין", "אין פעולה"
    except Exception as e:
        return False, f"state bridge נכשל: {e}", "ודא admin_web/state.py קיים ו־PYTHONPATH כולל את שורש הפרויקט"

def maybe_get_logs(base: str, limit: int = 200) -> Optional[list]:
    try:
        r = requests.get(base.rstrip("/") + "/api/logs?limit=%d&level_min=DEBUG" % limit, timeout=1.5)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return None

# ===== Report builder =====
def build_markdown_report(rows: list, env: dict, video_status: Dict[str,Any], payload_sample: Dict[str,Any], logs: Optional[list]) -> str:
    md = []
    md.append("# 🧪 Pipeline Diagnostics Report\n")
    md.append(f"- Generated: {ts()}\n")
    md.append("## תוצאות בדיקות\n")
    md.append("| בדיקה | תוצאה | פירוט | מה עושים |\n|---|---|---|---|")
    md.extend(rows)

    md.append("\n## סיכום סביבה")
    md.append("```json\n" + json.dumps(env, ensure_ascii=False, indent=2) + "\n```")

    md.append("\n## /api/video/status (תקציר)")
    md.append("```json\n" + json.dumps(video_status or {}, ensure_ascii=False, indent=2) + "\n```")

    md.append("\n## דוגמת Payload (אם התקבלה)")
    md.append("```json\n" + json.dumps(payload_sample or {}, ensure_ascii=False, indent=2) + "\n```")

    if logs:
        md.append("\n## לוגים אחרונים (אם זמינים)")
        try:
            # נציג רק 40 רשומות אחרונות כדי לא להכביד
            last = logs[-40:] if len(logs) > 40 else logs
            md.append("```json\n" + json.dumps(last, ensure_ascii=False, indent=2) + "\n```")
        except Exception:
            pass

    # Quick conclusions (actionable)
    md.append("\n## מסקנות מהירות")
    hints = []
    # דוגמאות להסברים מהירים לפי הממצאים:
    try:
        if not video_status or not video_status.get("running", False) and (video_status.get("fps", 0.0) == 0.0):
            hints.append("- נראה שאין פריימים נכנסים. ודא שהדפדפן/טלפון שולח ל־POST /api/ingest_frame וה־main לא חוסם.")
        if payload_sample and not payload_sample.get("metrics") and not payload_sample.get("mp"):
            hints.append("- payload התקבל אבל בלי מדידות. בדוק MediaPipe/KINEMATICS בלוגים (חפש WARN/ERROR).")
    except Exception:
        pass
    if not hints:
        hints.append("- אם משהו עדיין לא ברור—בדוק את השדות בלוגים וב־payload למעלה, זה יכוון לבעיה המדויקת.")

    md.extend(hints)
    return "\n".join(md)

# ===== Main flow =====
def main():
    ap = argparse.ArgumentParser(description="BodyPlus_XPro pipeline diagnostics")
    ap.add_argument("--base", default=os.getenv("SERVER_BASE_URL", "http://127.0.0.1:5000"), help="שורש השרת (ברירת מחדל http://127.0.0.1:5000)")
    ap.add_argument("--frame", default="", help="קובץ JPEG להזרקה (לא חובה)")
    ap.add_argument("--timeout", type=float, default=4.0, help="זמן המתנה ל-payload (שניות)")
    args = ap.parse_args()

    base = args.base
    rows = []
    env = {
        "base": base,
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "has_pil": _HAS_PIL,
    }

    # 1) Server /health
    ok, detail, fix = check_server_health(base)
    rows.append(fmt_row("Flask /health", ok, detail, fix))
    if not ok:
        # לא נמשיך — אין טעם כשאין שרת
        report = build_markdown_report(rows, env, {}, {}, None)
        path = os.path.join(ensure_report_dir(), f"diagnostics_{int(time.time())}.md")
        with open(path, "w", encoding="utf-8") as f: f.write(report)
        print("\n".join([r for r in rows]))
        print(f"\n📄 נשמר דוח: {path}")
        sys.exit(2)

    # 2) /api/video/status
    ok, vstat, detail, fix = check_video_status(base)
    rows.append(fmt_row("/api/video/status", ok, detail, fix))

    # 3) push ingest frame
    frame_bytes = None
    if args.frame:
        frame_bytes = read_file_bytes(args.frame)
        if not frame_bytes:
            rows.append(fmt_row("טעינת קובץ פריים", False, f"לא נקרא: {args.frame}", "בדוק את הנתיב/הרשאות"))
        else:
            rows.append(fmt_row("טעינת קובץ פריים", True, f"נקרא: {args.frame} ({len(frame_bytes)} bytes)", "אין פעולה"))
    ok_push, detail, fix = push_ingest_frame(base, frame_bytes)
    rows.append(fmt_row("POST /api/ingest_frame", ok_push, detail, fix))

    # 4) wait for payload
    endpoint = detect_payload_endpoint(base)
    ok_payload, payload, detail, fix = wait_for_payload(base, endpoint, timeout_sec=float(args.timeout))
    rows.append(fmt_row(f"GET {endpoint}", ok_payload, detail, fix))

    # 5) mediapipe local (לבדיקת התקנה בסביבה)
    ok_mp, detail_mp, fix_mp, mp_info = check_mediapipe_local()
    env.update(mp_info)
    rows.append(fmt_row("MediaPipe (ייבוא מקומי)", ok_mp, detail_mp, fix_mp))

    # 6) kinematics local
    ok_kin, detail_kin, fix_kin = check_kinematics_local()
    rows.append(fmt_row("KINEMATICS (ייבוא מקומי)", ok_kin, detail_kin, fix_kin))

    # 7) state bridge local
    ok_state, detail_state, fix_state = check_state_bridge_local()
    rows.append(fmt_row("admin_web.state (ייבוא מקומי)", ok_state, detail_state, fix_state))

    # 8) logs (optional)
    logs = maybe_get_logs(base)

    # Build report
    report = build_markdown_report(rows, env, vstat if isinstance(vstat, dict) else {}, payload if isinstance(payload, dict) else {}, logs)
    path = os.path.join(ensure_report_dir(), f"diagnostics_{int(time.time())}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)

    # Console summary
    print("\n=== תוצאות בדיקה (תקציר) ===")
    print("| בדיקה | תוצאה | פירוט | מה עושים |")
    print("|---|---|---|---|")
    for r in rows:
        print(r)
    print(f"\n📄 נשמר דוח: {path}")

    # Exit code hint
    exit_code = 0 if all(("| PASS |" in r) or ("Flask /health" in r) for r in rows) else 1
    sys.exit(exit_code)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Save crash report
        base = ensure_report_dir()
        crash = os.path.join(base, f"diagnostics_crash_{int(time.time())}.md")
        with open(crash, "w", encoding="utf-8") as f:
            f.write("# Crash in diagnostics\n\n```\n" + traceback.format_exc() + "\n```")
        print(f"❌ שגיאה לא מטופלת. דוח קריסה נשמר: {crash}")
        sys.exit(3)
