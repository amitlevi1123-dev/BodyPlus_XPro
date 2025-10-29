# -*- coding: utf-8 -*-
"""
בדיקת Health ל-RunPod / מקומי — זיהוי פורט שגוי (5000/8000) וסטטוס /healthz
============================================================================
מה הקובץ עושה?
- ניגש ל-URL בסיס (מקומי או ציבורי של RunPod) ובודק /healthz, /readyz, ו-/.
- מזהה אם השירות מאזין על פורט "שגוי" (למשל 5000 במקום 8000) ומדפיס הסבר ברור.
- מחזיר קוד יציאה 0 אם יש לפחות נתיב אחד שמחזיר 200, אחרת 1.
- אין תלות ב-requests; הכל ב-urllib (סטנדרט).

איך מריצים (דוגמאות):
1) מקומי (אם מריץ main.py על 5000):
   - Windows PowerShell:
       $env:PORT="5000"
       python tools\\test_health_check.py --local
   - או לציין ידנית:
       python tools\\test_health_check.py --base http://127.0.0.1:5000

2) מקומי עם Gunicorn על 8000:
       $env:PORT="8000"
       python tools\\test_health_check.py --local

3) ענן (RunPod) — עם ה-URL הציבורי (ללא פורט, הכלי ינסה 8000 ואז 5000 אם צריך):
       python tools\\test_health_check.py --base https://<your-runpod-public-host>

טיפים:
- ב-RunPod רצוי שהשירות יאזין על $PORT (בד"כ 8000) ושקיים /healthz שמחזיר 200 מהר.
- אם הכלי יזהה ש-8000 נכשל ו-5000 מצליח — זה אומר שהשרת עלה על פורט "שגוי" ביחס לקינפוג.
"""

from __future__ import annotations
import os
import sys
import argparse
import json
import time
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DEFAULT_PORT_CLOUD = 8000
ALT_PORT_LOCAL = 5000
PATHS = ["/healthz", "/readyz", "/"]

def _normalize_base(base: str, port: int | None) -> str:
    """
    מנרמל base כך שאם חסר פורט – נוסיף את הפורט המבוקש.
    אם יש כבר פורט ב-URL שניתן, נשאיר אותו.
    """
    parsed = urlparse(base)
    if not parsed.scheme:
        # אם נתנו רק '127.0.0.1' למשל – נהפוך ל-http://127.0.0.1
        base = "http://" + base
        parsed = urlparse(base)

    netloc = parsed.netloc
    if ":" in netloc:
        # כבר יש פורט
        return base

    if port is None:
        return base

    netloc = f"{parsed.hostname}:{port}"
    parsed = parsed._replace(netloc=netloc)
    return urlunparse(parsed)


def _try_get(url: str, timeout: float = 5.0) -> tuple[int | None, str | None]:
    """
    מבצע GET ומחזיר (status_code, body_snippet עד 200 תווים).
    אם נכשל – (None, str(error))
    """
    req = Request(url, headers={"User-Agent": "BodyPlus_XPro-HealthCheck/1.0"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            snippet = data[:200].decode("utf-8", errors="replace")
            return resp.getcode(), snippet
    except HTTPError as e:
        try:
            data = e.read()
            snippet = data[:200].decode("utf-8", errors="replace")
        except Exception:
            snippet = None
        return e.code, snippet
    except URLError as e:
        return None, str(e.reason)
    except Exception as e:
        return None, str(e)


def _check_paths(base: str) -> dict:
    results = {}
    for path in PATHS:
        url = base.rstrip("/") + path
        code, body = _try_get(url)
        results[path] = {"ok": (code == 200), "status": code, "body": body, "url": url}
    return results


def main():
    parser = argparse.ArgumentParser(description="BodyPlus_XPro — Health check (RunPod/Local)")
    parser.add_argument("--base", type=str, default=None,
                        help="Base URL (e.g., http://127.0.0.1:8000 or https://<public-runpod-host>)")
    parser.add_argument("--local", action="store_true",
                        help="Quick local mode: use 127.0.0.1 and PORT env (fallback 8000)")
    parser.add_argument("--expect-port", type=int, default=None,
                        help="Expected port (default: 8000 for cloud, 5000 for local main.py)")
    parser.add_argument("--timeout", type=float, default=5.0, help="HTTP timeout seconds (default 5)")
    args = parser.parse_args()

    # קביעת base ופורט צפוי
    if args.local and not args.base:
        env_port = int(os.getenv("PORT", str(DEFAULT_PORT_CLOUD)))
        base = f"http://127.0.0.1:{env_port}"
        expected_port = env_port
        mode = f"local(PORT={env_port})"
    else:
        base = args.base or os.getenv("RUNPOD_PUBLIC_URL") or f"http://127.0.0.1:{DEFAULT_PORT_CLOUD}"
        # אם המשתמש לא נתן expect-port:
        if args.expect_port is not None:
            expected_port = args.expect_port
        else:
            # אם base נראה כמו runpod/public – נצפה 8000; אחרת נשאיר None (ננסה שניהם)
            parsed = urlparse(base if "://" in base else "http://" + base)
            expected_port = DEFAULT_PORT_CLOUD if (parsed.hostname and "." in parsed.hostname) else None
        mode = "custom"

    print("==============================================================")
    print(" BodyPlus_XPro • Health Check")
    print("==============================================================")
    print(f"Mode      : {mode}")
    print(f"Base (raw): {base}")
    print(f"ExpectPort: {expected_port if expected_port else '(auto)'}")
    print("--------------------------------------------------------------")

    tried = []
    successes = []
    # ננסה קודם עם expected_port (אם הוגדר), אחרת ננסה 8000 ואז 5000
    port_candidates = []
    if expected_port:
        port_candidates = [expected_port]
    else:
        port_candidates = [DEFAULT_PORT_CLOUD, ALT_PORT_LOCAL]

    summary = []
    exit_ok = False

    for p in port_candidates:
        base_with_port = _normalize_base(base, p)
        print(f"\n🔎 Checking base: {base_with_port}")
        results = _check_paths(base_with_port)
        tried.append((base_with_port, results))

        # הדפסה מסודרת
        for path, info in results.items():
            ok = info["ok"]
            status = info["status"]
            print(f"  • {path:<8} → {'OK' if ok else 'FAIL'}  (status={status})  [{info['url']}]")

        # הצלחה אם לפחות אחד החזיר 200
        port_ok = any(info["ok"] for info in results.values())
        if port_ok:
            successes.append((p, results))
            exit_ok = True
            # לא שוברים; נדפיס סיכום גם עבור הניסיונות הנותרים

    print("\n==============================================================")
    # אבחון מהיר לגבי 5000/8000
    ports_ok = [p for p, _ in successes]
    if 8000 in ports_ok and 5000 in ports_ok:
        print("⚠️  גם 8000 וגם 5000 מחזירים 200. ודא שאין שני שרתים רצים במקביל.")
    elif 8000 in ports_ok:
        print("✅  השירות תקין על פורט 8000 (מצופה בענן).")
    elif 5000 in ports_ok:
        print("⚠️  נמצא שירות תקין על 5000 — כנראה רץ dev-server/port שגוי לענן.")
        print("   → בענן RunPod מומלץ להריץ Gunicorn על $PORT (בד״כ 8000) ולכוון Health ל-/healthz.")
    else:
        print("❌  לא נמצא נתיב בריא (200) על הפורטים שנבדקו.")

    # סיכום JSON קטן למי שרוצה לעבד תוצאות
    out = {
        "base_input": base,
        "ports_tried": port_candidates,
        "ok_ports": ports_ok,
        "trials": [
            {"base": b, "results": r} for (b, r) in tried
        ],
        "timestamp": int(time.time()),
    }
    print("--------------------------------------------------------------")
    print("JSON summary:")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    sys.exit(0 if exit_ok else 1)


if __name__ == "__main__":
    main()
