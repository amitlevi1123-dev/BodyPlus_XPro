#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/upload_video_check.py
בדיקות תקינות end-to-end:
- בדיקות נתיב קובץ (קיום, הרשאות, סיומת מותרת, גודל).
- בדיקת זמינות שרת (/healthz).
- בדיקת endpoints חיוניים (דף העלאה, /api/upload_video, /api/video/use_file, /api/video/status, /video/stream.mjpg).
- העלאה -> חיבור לקובץ -> המתנה ל-running -> שליפת פריים ראשון מה-MJPEG.

שימוש:
  python tests/upload_video_check.py "C:\\path\\to\\video.mp4" --host http://127.0.0.1:5000 --out first_frame.jpg
דרישות:
  pip install requests
"""
import os
import sys
import time
import argparse
import mimetypes
import requests
from urllib.parse import urljoin

ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".mjpg", ".mjpeg", ".webm"}
DEFAULT_MAX_MB = 500

def human_size(num):
    for unit in ["B","KB","MB","GB","TB"]:
        if num < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0

def check_file_path(path: str):
    # הרחבת ~ ומשתני סביבה, נירמול לנתיב אבסולוטי
    path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
    problems = []
    if not os.path.exists(path):
        problems.append(f"❌ קובץ לא קיים: {path}")
    else:
        if not os.path.isfile(path):
            problems.append(f"❌ הנתיב אינו קובץ רגיל: {path}")
        else:
            # הרשאות קריאה
            if not os.access(path, os.R_OK):
                problems.append(f"❌ אין הרשאת קריאה לקובץ: {path}")
            # סיומת
            ext = os.path.splitext(path)[1].lower()
            if ext not in ALLOWED_EXT:
                problems.append(f"⚠️ סיומת '{ext}' לא ברשימת ברירת המחדל {sorted(ALLOWED_EXT)} "
                                f"(השרת עשוי עדיין לתמוך אם שינית ALLOWED_EXT בצד שרת).")
            # גודל
            try:
                size = os.path.getsize(path)
                if size == 0:
                    problems.append("❌ גודל הקובץ 0B.")
                elif size > DEFAULT_MAX_MB * 1024 * 1024:
                    problems.append(f"⚠️ הקובץ גדול מ-{DEFAULT_MAX_MB}MB (אפשר לשנות MAX_UPLOAD_MB בשרת). "
                                    f"גודל: {human_size(size)}")
            except Exception as e:
                problems.append(f"⚠️ נכשל להשיג גודל קובץ: {e}")
    return path, problems

def get_json(url, timeout=10):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def check_server(host: str):
    problems = []
    # /healthz
    try:
        j = get_json(urljoin(host, "/healthz"), timeout=5)
        print(f"🩺 /healthz → ok={j.get('ok')} ver={j.get('ver')}")
    except Exception as e:
        problems.append(f"❌ שרת לא זמין או /healthz נכשל: {e}")
        return problems

    # דף העלאה (לא חובה, אבל נותן אינדיקציה טובות)
    try:
        r = requests.get(urljoin(host, "/admin/upload-video"), timeout=5)
        if r.status_code != 200:
            problems.append(f"⚠️ /admin/upload-video החזיר {r.status_code}")
        else:
            print("📄 /admin/upload-video זמין")
    except Exception as e:
        problems.append(f"⚠️ /admin/upload-video נכשל: {e}")

    # בדיקת /api/upload_video/status
    try:
        j = get_json(urljoin(host, "/api/upload_video/status"), timeout=5)
        if not isinstance(j, dict) or "ok" not in j:
            problems.append("⚠️ /api/upload_video/status לא החזיר אובייקט צפוי")
        else:
            print("ℹ️ /api/upload_video/status זמין")
    except Exception as e:
        problems.append(f"⚠️ /api/upload_video/status נכשל: {e}")

    # בדיקת /api/video/status
    try:
        j = get_json(urljoin(host, "/api/video/status"), timeout=5)
        if not isinstance(j, dict) or "ok" not in j:
            problems.append("⚠️ /api/video/status לא החזיר אובייקט צפוי")
        else:
            print("🎥 /api/video/status זמין")
    except Exception as e:
        problems.append(f"⚠️ /api/video/status נכשל: {e}")

    # בדיקת HEAD ל־/video/stream.mjpg (עשוי להיות 503 אם לא רץ—זה בסדר)
    try:
        r = requests.get(urljoin(host, "/video/stream.mjpg"), timeout=5, stream=True)
        print(f"🧪 /video/stream.mjpg → HTTP {r.status_code} (503 זה תקין כשאין סטרים)")
        r.close()
    except Exception as e:
        problems.append(f"⚠️ /video/stream.mjpg בדיקה נכשלה: {e}")
    return problems

def upload(host: str, path: str):
    url = urljoin(host, "/api/upload_video")
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = "video/*"
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, mime)}
        r = requests.post(url, files=files, timeout=180)
    r.raise_for_status()
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Upload failed: {j}")
    print(f"⬆️ הועלה: {j.get('file_name')} ({j.get('size_mb')}MB)")
    return j

def use_file(host: str):
    url = urljoin(host, "/api/video/use_file")
    r = requests.post(url, timeout=30)
    r.raise_for_status()
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"use_file failed: {j}")
    print(f"🎬 חובר לקובץ ({j.get('file_name')}) via {j.get('message')}")
    return j

def wait_running(host: str, timeout_s=12.0):
    url = urljoin(host, "/api/video/status")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = requests.get(url, timeout=5)
            if r.ok:
                j = r.json()
                opened = bool(j.get("opened"))
                running = bool(j.get("running"))
                fps = j.get("fps")
                print(f"   status: opened={opened} running={running} fps={fps}", end="\r", flush=True)
                if opened and running:
                    print()
                    return j
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError("video did not become running in time")

def grab_one_mjpeg_frame(host: str, out_path: str, timeout_s=10.0):
    url = urljoin(host, "/video/stream.mjpg")
    with requests.get(url, stream=True, timeout=timeout_s) as r:
        r.raise_for_status()
        buf = bytearray()
        soi = b"\xff\xd8"
        eoi = b"\xff\xd9"
        found_soi = False
        for chunk in r.iter_content(chunk_size=4096):
            if not chunk:
                continue
            buf.extend(chunk)
            if not found_soi:
                i = buf.find(soi)
                if i != -1:
                    buf = buf[i:]
                    found_soi = True
            if found_soi:
                j = buf.find(eoi)
                if j != -1:
                    frame = bytes(buf[: j + 2])
                    with open(out_path, "wb") as f:
                        f.write(frame)
                    return out_path
    raise RuntimeError("could not extract a JPEG frame from MJPEG stream")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="נתיב לקובץ וידאו (השתמש בנתיב אמיתי במחשב שלך)")
    ap.add_argument("--host", default="http://127.0.0.1:5000", help="בסיס ה-URL של השרת")
    ap.add_argument("--out", default="first_frame.jpg", help="קובץ פלט לפריים ראשון מה-MJPEG")
    args = ap.parse_args()

    # 1) בדיקות נתיב
    path, probs = check_file_path(args.video)
    if probs:
        print("\n".join(probs), file=sys.stderr)
        print("ℹ️ דוגמה ב-Windows:", r'python tests\upload_video_check.py "C:\Users\Owner\Videos\myclip.mp4"', file=sys.stderr)
        sys.exit(2)
    print(f"📂 קובץ: {path} ({human_size(os.path.getsize(path))})")

    # 2) בדיקת שרת
    srv_problems = check_server(args.host)
    if srv_problems:
        print("\n".join(srv_problems), file=sys.stderr)
        sys.exit(3)

    # 3) העלאה
    upload(args.host, path)

    # 4) חיבור לקובץ (מפעיל סטרים אוטומטית; לא צריך "להדליק מצלמה")
    use_file(args.host)

    # 5) המתנה להפעלה
    st = wait_running(args.host, timeout_s=15.0)
    print(f"✅ רץ. source={st.get('source')} fps={st.get('fps')} size={st.get('size')}")

    # 6) שליפת פריים ראשון מה-MJPEG
    out = os.path.abspath(args.out)
    grab_one_mjpeg_frame(args.host, out, timeout_s=12.0)
    print(f"🖼️ נשמר פריים ראשון: {out}")
    print(f"פתח לצפייה: {urljoin(args.host, '/video/stream')}")

if __name__ == "__main__":
    main()
