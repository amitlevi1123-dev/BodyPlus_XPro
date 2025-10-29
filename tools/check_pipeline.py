# -*- coding: utf-8 -*-
"""
tools/check_pipeline.py — בדיקת שרשרת הווידאו והמדדים (כולל זיהוי אובייקטים)
==========================================================================

מטרה: לוודא שכל החיבורים עובדים מקצה לקצה, וגם לזהות איפה זה נתקע אם לא.

מה נבדק?
1) /api/ingest_frame  — האם אפשר להזרים פריים מהדפדפן/תסריט.
2) /video/stream.mjpg — האם ה-MJPEG פעיל ומחזיר פריימים.
3) /api/payload_last  — האם יש Payload עם מדדים/שלד ממדיהפיפ.
4) /api/video/status  — תקציר סטטוס הווידאו (אם קיים בשרת).
5) זיהוי-אובייקטים (OD) — ננסה מספר endpoints תואמים ונבצע detect פעם אחת.

שימוש:
------
Windows PowerShell:
    $env:BASE = "http://127.0.0.1:5000"
    python tools\\check_pipeline.py

אפשר לקבוע timeout שניות:
    python tools\\check_pipeline.py --timeout 5

תלויות:
    pip install requests pillow

תוצרי ריצה:
    tools/diagnostics/Pipeline_Diagnostics.md  — דו"ח קריא
    tools/diagnostics/pipeline_snapshot.json   — סנאפשוט JSON
"""

from __future__ import annotations
import os, io, sys, json, time, textwrap, argparse, datetime
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except Exception:
    print("❌ חסר המודול 'requests'. הרץ: pip install requests")
    raise

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None

# ────────────────────────────────────────────────────────────────────────────
# קונפיג בסיסי
# ────────────────────────────────────────────────────────────────────────────
DEFAULT_BASE = os.environ.get("BASE", "http://127.0.0.1:5000")
TIMEOUT_DEFAULT = 4.0

OD_STATUS_CANDIDATES = [
    "/api/objdet/status",
    "/api/objdet/health",
    "/api/object/status",
    "/api/od/status",
]
OD_DETECT_CANDIDATES = [
    "/api/objdet/detect_once",
    "/api/objdet/detect",
    "/api/object/detect",
    "/api/od/detect",
]


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def make_test_jpeg(width: int = 640, height: int = 360) -> bytes:
    """יוצר תמונת מבחן JPEG בזיכרון (עם טקסט זמן)"""
    if Image is None:
        return b""
    img = Image.new("RGB", (width, height), color=(20, 20, 20))
    draw = ImageDraw.Draw(img)
    ts = _now()
    lines = ["BodyPlus_XPro • TEST FRAME", ts, "/api/ingest_frame"]
    y = 20
    for line in lines:
        draw.text((20, y), line, fill=(240, 240, 240))
        y += 24
    draw.rectangle([(width//4, height//3), (width*3//4, height*2//3)],
                   outline=(180, 220, 255), width=3)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def try_get_json(resp: requests.Response) -> Optional[Dict[str, Any]]:
    try:
        return resp.json()
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────────────
# בדיקות
# ────────────────────────────────────────────────────────────────────────────
def check_ingest(base: str, test_bytes: bytes, timeout: float):
    url = base.rstrip("/") + "/api/ingest_frame"
    info = {"url": url}
    try:
        files = {"frame": ("test.jpg", test_bytes, "image/jpeg")}
        r = requests.post(url, files=files, timeout=timeout)
        info["multipart_status"] = r.status_code
        j = try_get_json(r)
        if j: info["multipart_json"] = j
        if r.ok: return True, "OK (multipart)", info
        r2 = requests.post(url, data=test_bytes, headers={"Content-Type": "image/jpeg"}, timeout=timeout)
        info["raw_status"] = r2.status_code
        j2 = try_get_json(r2)
        if j2: info["raw_json"] = j2
        if r2.ok: return True, "OK (raw)", info
        return False, f"HTTP {r.status_code}/{r2.status_code}", info
    except Exception as e:
        return False, f"Exception: {e}", info


def check_mjpeg(base: str, timeout: float):
    url = base.rstrip("/") + "/video/stream.mjpg"
    info = {"url": url}
    try:
        r = requests.get(url, stream=True, timeout=timeout)
        info["status"] = r.status_code
        if not r.ok:
            return False, f"HTTP {r.status_code}", info
        chunk = next(r.iter_content(chunk_size=8192))
        info["first_chunk_len"] = len(chunk)
        has_jpeg_magic = b"\xff\xd8" in chunk and b"\xff\xd9" in chunk
        if has_jpeg_magic:
            return True, "OK (JPEG chunk)", info
        return False, "No JPEG magic in first chunk", info
    except Exception as e:
        return False, f"Exception: {e}", info


def check_payload(base: str, timeout: float):
    url = base.rstrip("/") + "/api/payload_last"
    info = {"url": url}
    deadline = time.time() + max(1.0, timeout)
    last_json = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=timeout)
            j = try_get_json(r)
            if j:
                last_json = j
                if len(j) > 0:
                    info["sample_keys"] = list(j.keys())[:10]
                    return True, "OK (payload present)", info
        except Exception:
            pass
        time.sleep(0.3)
    info["last_json_len"] = len(last_json or {})
    return False, "Empty payload (MediaPipe לא רץ או לא מחובר).", info


def check_video_status(base: str, timeout: float):
    url = base.rstrip("/") + "/api/video/status"
    info = {"url": url}
    try:
        r = requests.get(url, timeout=timeout)
        if not r.ok:
            return False, f"HTTP {r.status_code}", info
        j = try_get_json(r) or {}
        info.update({k: j.get(k) for k in ("opened","running","fps","size","payload_age_sec","mode","ffmpeg") if k in j})
        return True, "OK", info
    except Exception as e:
        return False, f"Exception: {e}", info


def discover_od_status(base: str, timeout: float):
    info = {"tried": []}
    for path in OD_STATUS_CANDIDATES:
        url = base.rstrip("/") + path
        try:
            r = requests.get(url, timeout=timeout)
            info["tried"].append({"url": url, "code": r.status_code})
            if r.ok and try_get_json(r) is not None:
                return url, info
        except Exception as e:
            info["tried"].append({"url": url, "err": str(e)})
    return None, info


def check_od_detect(base: str, test_bytes: bytes, timeout: float):
    info = {"candidates": OD_DETECT_CANDIDATES}
    for path in OD_DETECT_CANDIDATES:
        url = base.rstrip("/") + path
        try:
            files = {"image": ("test.jpg", test_bytes, "image/jpeg")}
            r = requests.post(url, files=files, timeout=timeout)
            info[url] = r.status_code
            if r.ok:
                j = try_get_json(r) or {}
                boxes = j.get("boxes") or j.get("detections") or []
                return True, f"OK (detections={len(boxes)})", info
        except Exception as e:
            info[url] = {"error": str(e)}
    return False, "OD detect endpoint not found/failed", info


def write_report(report: Dict[str, Any]) -> str:
    out_dir = os.path.join("tools", "diagnostics")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, "Pipeline_Diagnostics.md")
    json_path = os.path.join(out_dir, "pipeline_snapshot.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    lines = [f"# 🧪 Pipeline Diagnostics Report\n- Generated: {_now()}\n- Base: {report.get('base')}\n"]

    def add(title, ok, desc, info):
        emoji = "✅" if ok else "❌"
        lines.append(f"\n## {emoji} {title}\n**Result:** {desc}\n")
        pretty = json.dumps(info, ensure_ascii=False, indent=2)
        lines.append(f"<details><summary>Details</summary>\n\n```json\n{pretty}\n```\n</details>\n")

    add("/api/ingest_frame", *report["ingest"])
    add("/video/stream.mjpg", *report["mjpeg"])
    add("/api/payload_last", *report["payload"])
    add("/api/video/status", *report["video_status"])
    add("Object Detection: detect_once", *report["od_detect"])

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return md_path


def main():
    ap = argparse.ArgumentParser(description="BodyPlus_XPro — Pipeline Check")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--timeout", type=float, default=TIMEOUT_DEFAULT)
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=360)
    args = ap.parse_args()

    base = args.base
    timeout = args.timeout

    print(f"\\n🚀 BodyPlus_XPro Pipeline Check — {base}\\n")
    test_bytes = make_test_jpeg(args.w, args.h)
    report = {"base": base, "generated": _now()}

    report["ingest"] = check_ingest(base, test_bytes, timeout)
    report["mjpeg"] = check_mjpeg(base, timeout)
    report["payload"] = check_payload(base, timeout)
    report["video_status"] = check_video_status(base, timeout)
    report["od_status_url"], _ = discover_od_status(base, timeout)
    report["od_detect"] = check_od_detect(base, test_bytes, timeout)

    path = write_report(report)
    print(f"📄 דו\"ח נכתב: {path}\\n✅ סיום הבדיקה.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\nהופסק על ידי המשתמש.")
