# -*- coding: utf-8 -*-
# =============================================================================
# 🧪 diag_server_video.py — בדיקת שרת וידאו (בריאות → start → ingest → סטרים)
# -----------------------------------------------------------------------------
# שימוש:
#   python tools/diag/diag_server_video.py --base http://127.0.0.1:8080 --mode auto
#   מצבים: auto | camera | file | synthetic | ingest-only
# הערות:
# • מתקן בעיית base64 padding.
# • timeout נכון לסטרימינג (connect=5s, read=30s).
# =============================================================================

from __future__ import annotations
import argparse, base64, io, json, sys, time
from typing import Dict, Optional, Tuple

import requests

DEFAULTS = dict(frames=120, fps=12, timeout=8.0)
# JPEG קטן בבסיס64 (עם תיקון padding)
_EMBEDDED_JPEG_B64 = (
    b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxISEhUTEhMVFRUVFRUVFRUVFRUVFRUWFxUVFRUY"
    b"HSggGBolGxUVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGi0fHyUtLS0tLS0tLS0tLS0t"
    b"LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAJYA2gMBIgACEQEDEQH/xAAX"
    b"AQEBAQEAAAAAAAAAAAAAAAAAAgMF/8QAHxAAAgICAwEAAAAAAAAAAAAAAQIAAxESITEEUXGB/8QA"
    b"FQEBAQAAAAAAAAAAAAAAAAAABQb/xAAZEQADAAMAAAAAAAAAAAAAAAAAARECEhP/2gAMAwEAAhED"
    b"EQAAAPcAAAAAAABnq0sZlq0sZlq0sZlq0sZlq0sZlq0sZlq0sZlq0sYAAAAAAAAB3w7DqPp9f7cY"
    b"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//Z"
)

def _b64fix(b: bytes) -> bytes:
    return base64.b64decode(b + b'=' * (-len(b) % 4))

def _now_ms() -> int: return int(time.time() * 1000)
def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S"); print(f"[{ts}] {msg}", flush=True)

def check_health(base: str, timeout: float) -> Tuple[bool, Dict[str, str]]:
    results = {}; ok = True
    for ep in ("/version", "/healthz"):
        try:
            r = requests.get(f"{base}{ep}", timeout=timeout)
            results[ep] = f"{r.status_code}"
            if r.status_code != 200: ok = False
        except Exception as e:
            results[ep] = f"ERROR: {e}"; ok = False
    return ok, results

def try_start_camera(base: str, timeout: float) -> Tuple[bool, str]:
    try:
        r = requests.post(f"{base}/api/video/start", json={}, timeout=timeout)
        if r.status_code in (200, 202, 204): return True, f"started (camera) — {r.status_code}"
        return False, f"HTTP {r.status_code} body={r.text[:200]}"
    except Exception as e:
        return False, f"ERROR: {e}"

def try_use_file(base: str, timeout: float) -> Tuple[bool, str]:
    try:
        r = requests.post(f"{base}/api/video/use_file", json={}, timeout=timeout)
        if r.status_code in (200, 202, 204): return True, f"started (file) — {r.status_code}"
        return False, f"HTTP {r.status_code} body={r.text[:200]}"
    except Exception as e:
        return False, f"ERROR: {e}"

def push_synthetic_frames(base: str, n_frames: int, fps: int, timeout: float) -> Tuple[bool, str]:
    url = f"{base}/api/ingest_frame"
    jpeg_bytes = _b64fix(_EMBEDDED_JPEG_B64)
    delay = 1.0 / max(1, fps)
    sent = 0
    for i in range(n_frames):
        files = {"frame": ("frame.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        data = {"ts": str(_now_ms())}
        try:
            r = requests.post(url, files=files, data=data, timeout=timeout)
            if r.status_code != 200:
                return False, f"ingest_frame HTTP {r.status_code} body={r.text[:120]}"
            sent += 1
        except Exception as e:
            return False, f"ingest_frame ERROR at #{i}: {e}"
        time.sleep(delay)
    return True, f"ingested {sent} frames @ ~{fps} FPS"

def poll_mjpeg(base: str, seconds: int, timeout: float) -> Tuple[bool, str, int]:
    url = f"{base}/video/stream.mjpg"
    start = time.time(); bytes_seen = 0; markers = 0
    try:
        # connect=5s, read=30s כדי לא ליפול ל-timeout בזמן סטרים
        with requests.get(url, stream=True, timeout=(5, 30)) as r:
            if r.status_code != 200:
                return False, f"stream.mjpg HTTP {r.status_code}", 0
            for chunk in r.iter_content(chunk_size=4096):
                if not chunk: continue
                bytes_seen += len(chunk)
                if b"\xff\xd8" in chunk:  # סימן תחילת JPEG
                    markers += 1
                if time.time() - start > seconds:
                    break
    except Exception as e:
        return False, f"stream.mjpg ERROR: {e}", 0
    if markers > 0 and bytes_seen > 0:
        return True, f"stream ok (~{markers} JPEG markers, {bytes_seen} bytes)", markers
    return False, f"no frames (bytes={bytes_seen}, markers={markers})", markers

def get_status(base: str, timeout: float) -> Tuple[bool, Optional[Dict]]:
    try:
        r = requests.get(f"{base}/api/video/status", timeout=timeout)
        if r.status_code != 200: return False, None
        return True, r.json()
    except Exception:
        return False, None

def main():
    ap = argparse.ArgumentParser(description="BodyPlus_XPro — דיאגנוסטיקת וידאו")
    ap.add_argument("--base", required=True, help="http://127.0.0.1:8080 או URL ציבורי")
    ap.add_argument("--mode", default="auto",
                    choices=["auto", "camera", "file", "synthetic", "ingest-only"])
    ap.add_argument("--frames", type=int, default=DEFAULTS["frames"])
    ap.add_argument("--fps", type=int, default=DEFAULTS["fps"])
    ap.add_argument("--timeout", type=float, default=DEFAULTS["timeout"])
    ap.add_argument("--stream-seconds", type=int, default=5)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    timeout = args.timeout
    summary: Dict[str, str] = {}

    _log(f"בדיקת שרת ב־{base}")
    ok_health, health_map = check_health(base, timeout)
    for k, v in health_map.items(): summary[k] = v
    _log(f"בריאות: {'OK' if ok_health else 'FAIL'} — {health_map}")

    st_ok, st_json = get_status(base, timeout)
    if st_ok:
        summary["/api/video/status"] = "200"
        _log(f"סטטוס וידאו: {json.dumps(st_json, ensure_ascii=False)}")
    else:
        summary["/api/video/status"] = "N/A"

    started = False
    start_note = ""

    def _start_camera_then_stream() -> bool:
        nonlocal started, start_note
        cam_ok, cam_note = try_start_camera(base, timeout)
        if cam_ok:
            started, start_note = True, cam_note
            _log(f"הפעלת מצלמה: {cam_note}")
            time.sleep(1.0)
            return True
        _log(f"נכשל להפעיל מצלמה: {cam_note}"); return False

    def _use_file_then_stream() -> bool:
        nonlocal started, start_note
        f_ok, f_note = try_use_file(base, timeout)
        if f_ok:
            started, start_note = True, f_note
            _log(f"הפעלת קובץ וידאו: {f_note}")
            time.sleep(1.0)
            return True
        _log(f"נכשל להפעיל קובץ: {f_note}"); return False

    if args.mode in ("auto", "camera"):
        if not _start_camera_then_stream():
            if args.mode == "camera":
                summary["start_mode"] = "camera: FAIL"
            else:
                _log("auto: מעבר לניסיון קובץ...");
                if not _use_file_then_stream():
                    _log("auto: מעבר להזרקה סינתטית...")
                    s_ok, s_note = push_synthetic_frames(base, args.frames, args.fps, timeout)
                    started, start_note = s_ok, f"synthetic: {s_note}"; _log(start_note)
    elif args.mode == "file":
        if not _use_file_then_stream():
            summary["start_mode"] = "file: FAIL"
    elif args.mode in ("synthetic", "ingest-only"):
        s_ok, s_note = push_synthetic_frames(base, args.frames, args.fps, timeout)
        started, start_note = s_ok, f"{args.mode}: {s_note}"; _log(start_note)

    if start_note: summary["start_note"] = start_note

    stream_ok = False; frame_count = 0
    if args.mode != "ingest-only":
        _log(f"בדיקת סטרים MJPEG ל-{args.stream_seconds} שנ׳ ...")
        stream_ok, stream_note, frame_count = poll_mjpeg(base, args.stream_seconds, timeout)
        summary["/video/stream.mjpg"] = "OK" if stream_ok else "FAIL"
        summary["stream_note"] = stream_note
        _log(f"סטרים: {stream_note}")

    print("\n" + "=" * 72)
    print("📋 SUMMARY")
    print("=" * 72)
    for k in sorted(summary.keys()):
        print(f"{k:24} : {summary[k]}")
    print("-" * 72)
    overall = ok_health and (started or args.mode == "ingest-only") and (stream_ok or args.mode == "ingest-only")
    print(f"OVERALL: {'PASS ✅' if overall else 'FAIL ❌'}")
    print("=" * 72)

    sys.exit(0 if overall else 1)

if __name__ == "__main__":
    main()
