# -*- coding: utf-8 -*-
"""
diag_video.py — בדיקה מקיפה לשרשרת הווידאו
-----------------------------------------
מה הוא בודק:
1) /version, /healthz
2) /api/video/status (opened/running/fps/size)
3) /video/stream.mjpg — תוכן-טיפוס של סטרים (multipart/x-mixed-replace) וניסיון לקרוא חתיכה
4) אם אין סטרים: מנסה להפעיל מצלמה דרך /api/video/start
5) אם עדיין אין סטרים: מזריק ingest דמי (JPEG שחור) ל-/api/ingest_frame כמה פעמים, ובודק שוב סטרים
6) מדפיס סיכום מפורט + “מה לתקן עכשיו”

תלויות: requests, pillow (Pillow)
התקנה:  pip install requests pillow
הרצה:    python tools/diag_video.py --base http://127.0.0.1:5000
"""

import sys, time, argparse
import requests
from io import BytesIO

# PIL ליצירת JPEG דמי
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None

DEFAULT_BASE = "http://127.0.0.1:5000"

def hr(msg=""):
    print("="*70 if not msg else f"\n{'='*12} {msg} {'='*12}")

def get_json(base, path, timeout=4):
    url = base.rstrip("/") + path
    try:
        r = requests.get(url, timeout=timeout)
        ok = r.ok
        j = r.json() if ok else None
        return ok, r.status_code, j, r.text
    except Exception as e:
        return False, 0, None, str(e)

def post_json(base, path, body=None, timeout=6):
    url = base.rstrip("/") + path
    try:
        r = requests.post(url, json=(body or {}), timeout=timeout)
        ok = r.ok
        j = r.json() if ok else None
        raw = r.text
        return ok, r.status_code, j, raw
    except Exception as e:
        return False, 0, None, str(e)

def check_stream_headers(base, path="/video/stream.mjpg", timeout=3):
    url = base.rstrip("/") + path
    try:
        # בקשה “רגילה” (לא stream=True) לקבלת כותרות
        r = requests.get(url, timeout=timeout, stream=True)
        ct = r.headers.get("Content-Type","")
        ok = r.ok and "multipart/x-mixed-replace" in ct
        return ok, r.status_code, ct, r
    except Exception as e:
        return False, 0, str(e), None

def try_read_stream_chunk(resp, max_bytes=4096, timeout=5.0):
    """קורא חתיכה קטנה מהסטרים כדי לוודא שהוא “חי”. מחזיר (ok, read_bytes)."""
    if resp is None:
        return False, 0
    start = time.time()
    read = 0
    try:
        resp.raise_for_status()
    except Exception:
        return False, 0
    try:
        for chunk in resp.iter_content(chunk_size=1024):
            if chunk:
                read += len(chunk)
            if read >= max_bytes:
                break
            if (time.time() - start) > timeout:
                break
    except Exception:
        pass
    return (read > 0), read

def make_dummy_jpeg(w=1280, h=720, text="INGEST TEST"):
    if Image is None:
        return None
    im = Image.new("RGB", (w, h), (0, 0, 0))
    dr = ImageDraw.Draw(im)
    txt = f"{text}\n{time.strftime('%H:%M:%S')}"
    try:
        # פונט מערכת / דיפולט
        dr.text((20, 20), txt, fill=(255, 255, 255))
    except Exception:
        pass
    bio = BytesIO()
    im.save(bio, format="JPEG", quality=80)
    return bio.getvalue()

def push_ingest_frames(base, n=5, delay=0.05):
    url = base.rstrip("/") + "/api/ingest_frame"
    sent = 0
    last_resp = None
    blob = make_dummy_jpeg() or b"\xff\xd8\xff"  # אם אין PIL, נשלח header דמי (יהיה 400)
    for i in range(n):
        try:
            r = requests.post(url, data=blob, headers={"Content-Type":"image/jpeg"}, timeout=4)
            last_resp = r
            if r.ok:
                sent += 1
        except Exception:
            pass
        time.sleep(delay)
    return sent, last_resp

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="כתובת השרת (למשל http://127.0.0.1:5000)")
    ap.add_argument("--start", action="store_true", help="לנסות להפעיל מצלמה אם אין סטרים")
    ap.add_argument("--ingest", action="store_true", help="לנסות להזרים ingest דמי אם אין סטרים")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    results = {"base": base}

    hr("BASIC")
    print("Base:", base)

    # 1) /version
    ok, code, j, raw = get_json(base, "/version", timeout=4)
    print("GET /version:", ok, code, (j or raw))
    results["version"] = dict(ok=ok, code=code, j=j)

    # 2) /healthz
    ok, code, j, raw = get_json(base, "/healthz", timeout=4)
    print("GET /healthz:", ok, code, (j or raw))
    results["healthz"] = dict(ok=ok, code=code, j=j)

    # 3) /api/video/status
    ok, code, j, raw = get_json(base, "/api/video/status", timeout=4)
    print("GET /api/video/status:", ok, code)
    if j:
        print("  opened:", j.get("opened"), "| running:", j.get("running"), "| fps:", j.get("fps"), "| size:", j.get("size"), "| source:", j.get("source"))
    else:
        print(" ", raw)
    results["status"] = dict(ok=ok, code=code, j=j)

    # 4) /video/stream.mjpg — כותרות
    hr("STREAM HEADERS")
    s_ok, s_code, ct, resp = check_stream_headers(base, "/video/stream.mjpg?hud=1", timeout=4)
    print("HEAD/GET /video/stream.mjpg?hud=1 →", s_ok, s_code, "| Content-Type:", ct)
    results["stream_headers"] = dict(ok=s_ok, code=s_code, ct=ct)

    # 5) נסה לקרוא חתיכה מהסטרים
    chunk_ok = False
    read_len = 0
    if s_ok and resp is not None:
        chunk_ok, read_len = try_read_stream_chunk(resp, max_bytes=4096, timeout=5.0)
        try:
            resp.close()
        except Exception:
            pass
    print("READ stream chunk:", chunk_ok, "| bytes:", read_len)
    results["stream_read"] = dict(ok=chunk_ok, bytes=read_len)

    # אם אין סטרים — אולי להפעיל מצלמה?
    did_start = False
    if (not s_ok or not chunk_ok) and args.start:
        hr("TRY START CAMERA")
        ok, code, j, raw = post_json(base, "/api/video/start", body={"camera_index": 0, "show_preview": False}, timeout=8)
        print("POST /api/video/start:", ok, code, (j or raw))
        did_start = ok

        # בדיקה מחדש של הסטרים
        s_ok, s_code, ct, resp = check_stream_headers(base, "/video/stream.mjpg?hud=1", timeout=4)
        print("STREAM after start →", s_ok, s_code, "| Content-Type:", ct)
        if s_ok and resp:
            chunk_ok, read_len = try_read_stream_chunk(resp, max_bytes=4096, timeout=5.0)
            try:
                resp.close()
            except Exception:
                pass
            print("READ chunk after start:", chunk_ok, "| bytes:", read_len)

    # אם עדיין אין סטרים — ננסה ingest דמי
    did_ingest = False
    if (not s_ok or not chunk_ok) and args.ingest:
        hr("TRY DUMMY INGEST")
        sent, last = push_ingest_frames(base, n=8, delay=0.05)
        print(f"POST /api/ingest_frame × {sent} OK (out of ~8)")
        did_ingest = sent > 0

        # בדוק שוב סטרים (במצב fallback ingest)
        s_ok, s_code, ct, resp = check_stream_headers(base, "/video/stream.mjpg?hud=1", timeout=4)
        print("STREAM after ingest →", s_ok, s_code, "| Content-Type:", ct)
        if s_ok and resp:
            chunk_ok, read_len = try_read_stream_chunk(resp, max_bytes=4096, timeout=5.0)
            try:
                resp.close()
            except Exception:
                pass
            print("READ chunk after ingest:", chunk_ok, "| bytes:", read_len)

    # סיכום והמלצות
    hr("SUMMARY")
    st = results.get("status", {}).get("j") or {}
    opened = bool(st.get("opened"))
    running = bool(st.get("running"))
    fps = st.get("fps")
    size = st.get("size")
    print(f"Camera opened={opened} running={running} fps={fps} size={size}")
    print(f"Stream headers OK={s_ok}  chunk read OK={chunk_ok}")
    print(f"Did start camera? {did_start}  | Did dummy ingest? {did_ingest}")

    hr("WHAT TO FIX (next steps)")
    if s_ok and chunk_ok:
        print("✅ הסטרים עובד. אם לא רואים בדף /video — בדוק קאש/אבטחה בדפדפן.")
    else:
        if not opened or not running:
            print("• המצלמה לא רצה לפי /api/video/status → נסה:")
            print("   - להריץ עם --start בסקריפט הזה (או POST /api/video/start)")
            print("   - לוודא שלמחשב יש מצלמה זמינה ולא תפוסה ע״י אפליקציה אחרת")
        print("• /video/stream.mjpg לא מחזיר multipart/x-mixed-replace או לא מצליחים לקרוא chunk.")
        print("   - בדוק לוגים בטרמינל של server.py")
        print("   - אם זה רק בדף, פתח ישירות:  {}/video/stream.mjpg?hud=1".format(base))
        print("   - אם אתה עובד דרך טלפון/דפדפן אחר — ודא שה־BASE נכון ונגיש (ללא פרוקסי חוסם).")
        print("• אפשר להשתמש ב-ingest כגיבוי: פתח {} /capture ושדר לפה.".format(base))
    print("\nסוף.\n")

if __name__ == "__main__":
    main()
