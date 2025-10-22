#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/server_paths_check.py
בדיקת נתיבים/Endpoints ללא העלאת קובץ:
- /healthz
- /admin/upload-video (עמוד הטאב)
- /api/upload_video/status
- /api/video/status
- /video/stream.mjpg (עשוי להחזיר 503 אם אין סטרים — זה תקין)
- דפי בסיס: /, /dashboard, /video, /settings

שימוש:
  python tests/server_paths_check.py --host http://127.0.0.1:5000

דרישות:
  pip install requests
"""
import argparse
import sys
import requests
from urllib.parse import urljoin

def check_get(host, path, ok_codes={200}, allow_503=False, timeout=6, stream=False):
    url = urljoin(host, path)
    r = requests.get(url, timeout=timeout, stream=stream)
    if allow_503 and r.status_code == 503:
        return r, True, f"HTTP {r.status_code} (מותר כאן)"
    ok = r.status_code in ok_codes
    return r, ok, f"HTTP {r.status_code}"

def expect_json(r):
    try:
        return True, r.json()
    except Exception as e:
        return False, f"לא JSON: {e}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="http://127.0.0.1:5000", help="בסיס ה-URL של השרת")
    args = ap.parse_args()
    host = args.host.rstrip("/")

    failures = 0
    def fail(msg):
        nonlocal failures
        print("❌", msg)
        failures += 1

    def ok(msg):
        print("✅", msg)

    print(f"🔗 Host: {host}")

    # 1) /healthz
    try:
        r, good, note = check_get(host, "/healthz")
        if not good: fail(f"/healthz נכשל: {note}")
        else:
            j_ok, j = expect_json(r)
            if not j_ok: fail(f"/healthz: {j}")
            else:
                ok(f"/healthz → ok={j.get('ok')} ver={j.get('ver')} now={j.get('now')}")
    except Exception as e:
        fail(f"/healthz חריג: {e}")

    # 2) עמוד העלאה
    try:
        r, good, note = check_get(host, "/admin/upload-video", ok_codes={200})
        if not good: fail(f"/admin/upload-video → {note}")
        else: ok("/admin/upload-video זמין")
    except Exception as e:
        fail(f"/admin/upload-video חריג: {e}")

    # 3) סטטוס העלאה
    try:
        r, good, note = check_get(host, "/api/upload_video/status")
        if not good: fail(f"/api/upload_video/status → {note}")
        else:
            j_ok, j = expect_json(r)
            if not j_ok: fail(f"/api/upload_video/status: {j}")
            else:
                fields = ["ok","last_file","last_ok","last_err","ts"]
                missing = [k for k in fields if k not in j]
                if missing:
                    fail(f"/api/upload_video/status חסר שדות: {missing}")
                else:
                    ok("/api/upload_video/status זמין (מבנה תקין)")
    except Exception as e:
        fail(f"/api/upload_video/status חריג: {e}")

    # 4) סטטוס וידאו
    try:
        r, good, note = check_get(host, "/api/video/status")
        if not good: fail(f"/api/video/status → {note}")
        else:
            j_ok, j = expect_json(r)
            if not j_ok: fail(f"/api/video/status: {j}")
            else:
                fields = ["ok","opened","running","fps","size","source"]
                missing = [k for k in fields if k not in j]
                if missing:
                    fail(f"/api/video/status חסר שדות: {missing}")
                else:
                    ok(f"/api/video/status זמין (opened={j.get('opened')} running={j.get('running')})")
    except Exception as e:
        fail(f"/api/video/status חריג: {e}")

    # 5) סטרים MJPEG (503 תקין כשאין מקור פעיל)
    try:
        r, good, note = check_get(host, "/video/stream.mjpg", ok_codes={200}, allow_503=True, stream=True)
        if not good: fail(f"/video/stream.mjpg → {note}")
        else:
            ok(f"/video/stream.mjpg זמין מבחינת שרת ({note})")
        r.close()
    except Exception as e:
        fail(f"/video/stream.mjpg חריג: {e}")

    # 6) דפי בסיס
    for path, label in [("/","/ (redirect לדשבורד)"),
                        ("/dashboard","/dashboard"),
                        ("/video","/video"),
                        ("/settings","/settings")]:
        try:
            r, good, note = check_get(host, path, ok_codes={200,302})
            if not good:
                fail(f"{label} → {note}")
            else:
                ok(f"{label} זמין ({note})")
        except Exception as e:
            fail(f"{label} חריג: {e}")

    print("\nסיכום:")
    if failures:
        print(f"❗ נמצאו {failures} בעיות. בדוק את הלוגים של השרת ואת רישום ה-Blueprints.")
        sys.exit(1)
    else:
        print("🎉 כל הנתיבים העיקריים זמינים ותקינים.")
        sys.exit(0)

if __name__ == "__main__":
    main()
