#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/upload_video_smoke.py
בדיקת עשן: העלאת וידאו -> חיבור לקובץ -> וידוא ריצה -> שליפת פריים ראשון מה-MJPEG

תלויות:
  pip install requests

שימוש:
  python tests/upload_video_smoke.py /path/to/video.mp4 --host http://127.0.0.1:5000
"""

import sys, os, time, argparse, requests

def upload_file(host: str, path: str):
    url = f"{host}/api/upload_video"
    with open(path, "rb") as f:
        files = {"file": (os.path.basename(path), f, "video/*")}
        r = requests.post(url, files=files, timeout=120)
    r.raise_for_status()
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Upload failed: {j}")
    print(f"✅ Uploaded: {j.get('file_name')} ({j.get('size_mb')} MB)")
    return j

def connect_use_file(host: str):
    url = f"{host}/api/video/use_file"
    r = requests.post(url, timeout=30)
    r.raise_for_status()
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"use_file failed: {j}")
    print(f"🎬 Connected to file via: {j.get('message')}  ({j.get('file_name')})")
    return j

def wait_running(host: str, timeout_s: float = 10.0):
    url = f"{host}/api/video/status"
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
                    print()  # newline
                    return j
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError("video did not become running in time")

def grab_one_mjpeg_frame(host: str, out_path: str, timeout_s: float = 10.0):
    """
    פותח /video/stream.mjpg ושולף פריים JPEG ראשון ע"י חיפוש חתימות SOI/EOI.
    לא תלוי ב-opencv.
    """
    url = f"{host}/video/stream.mjpg"
    with requests.get(url, stream=True, timeout=timeout_s) as r:
        r.raise_for_status()
        buf = bytearray()
        soi = b"\xff\xd8"  # Start Of Image
        eoi = b"\xff\xd9"  # End Of Image
        found_soi = False
        for chunk in r.iter_content(chunk_size=4096):
            if not chunk:
                continue
            buf.extend(chunk)
            if not found_soi:
                i = buf.find(soi)
                if i != -1:
                    buf = buf[i:]  # חתוך עד תחילת התמונה
                    found_soi = True
            if found_soi:
                j = buf.find(eoi)
                if j != -1:
                    frame = bytes(buf[: j + 2])  # כולל EOI
                    with open(out_path, "wb") as f:
                        f.write(frame)
                    return out_path
    raise RuntimeError("could not extract a JPEG frame from MJPEG stream")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="נתיב לקובץ וידאו (mp4/mov/avi/mkv/mjpg/mjpeg/webm)")
    ap.add_argument("--host", default="http://127.0.0.1:5000", help="שרת ה-API")
    ap.add_argument("--out", default="first_frame.jpg", help="קובץ פלט לפריים הראשון")
    args = ap.parse_args()

    path = os.path.abspath(args.video)
    if not os.path.isfile(path):
        print(f"❌ קובץ לא קיים: {path}", file=sys.stderr)
        sys.exit(2)

    print(f"🔗 Host: {args.host}")
    print(f"📦 Uploading: {path}")

    # 1) העלאה
    upload_file(args.host, path)

    # 2) חיבור לקובץ (מפעיל אוטומטית start_auto_capture)
    connect_use_file(args.host)

    # 3) המתנה ל-running
    status = wait_running(args.host, timeout_s=12.0)
    print(f"✅ Running. source={status.get('source')} fps={status.get('fps')} size={status.get('size')}")

    # 4) שליפת פריים ראשון מה-MJPEG
    out_jpg = os.path.abspath(args.out)
    grab_one_mjpeg_frame(args.host, out_jpg, timeout_s=10.0)
    print(f"🖼️  Saved first MJPEG frame to: {out_jpg}")

    print("\n🎉 בדיקה הושלמה. אפשר גם לפתוח בדפדפן:", f"{args.host}/video/stream")

if __name__ == "__main__":
    main()
