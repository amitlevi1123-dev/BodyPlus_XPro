# -*- coding: utf-8 -*-
"""
tools/check_video_file_mode.py — דוח התאמה ל"וידאו מקובץ כאילו מצלמה" (ללא OpenCV)
-------------------------------------------------------------------------------
מה זה עושה:
- סורק את עץ הפרויקט ומחפש:
  • app/ui/video.py או מודול עם get_streamer()
  • read_frame() שמזינה את /video/stream.mjpg (בדרך כלל מחזירה (ok, bytes))
  • routes ל: /api/video/start_file /api/video/start_camera /api/video/upload_and_play
  • partials בדשבורד + static/js
  • תלויות: FFmpeg, Pillow
- מדפיס "FOUND"/"MISSING" והמלצות מינימליות לשילוב.

הרצה:
  python tools/check_video_file_mode.py
"""
from __future__ import annotations
import os, re, sys, json, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # שורש הפרויקט
REPORT = {"files":{}, "endpoints":{}, "templates":{}, "deps":{}, "notes":[]}

def _exists(path: Path) -> bool:
    return path.exists()

def _grep(patterns, paths):
    pat = re.compile(patterns, re.MULTILINE)
    hits = []
    for p in paths:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if pat.search(txt):
            hits.append(p)
    return hits

def _find_candidates(globlist):
    out = []
    for g in globlist:
        out.extend(ROOT.glob(g))
    return [p for p in out if p.is_file()]

def check_streamer():
    # מחפשים קובץ שיש בו get_streamer
    cands = _find_candidates([
        "app/ui/video.py",
        "app/ui/*.py",
        "app/**/*.py",
    ])
    hits = _grep(r"def\s+get_streamer\s*\(", cands)
    REPORT["files"]["get_streamer"] = [str(p.relative_to(ROOT)) for p in hits]
    # מחפשים read_frame
    hits2 = _grep(r"def\s+read_frame\s*\(", cands)
    REPORT["files"]["read_frame"] = [str(p.relative_to(ROOT)) for p in hits2]

def check_routes():
    cands = _find_candidates([
        "server.py",
        "routes/**/*.py",
        "app/**/*.py",
    ])
    for ep, pat in {
        "/api/video/start_file": r"/api/video/start_file",
        "/api/video/start_camera": r"/api/video/start_camera",
        "/api/video/upload_and_play": r"/api/video/upload_and_play",
        "/video/stream.mjpg": r"/video/stream\.mjpg",
    }.items():
        hits = _grep(pat, cands)
        REPORT["endpoints"][ep] = [str(p.relative_to(ROOT)) for p in hits]

def check_templates():
    tpls = _find_candidates([
        "templates/**/*.html",
        "admin_web/templates/**/*.html",
    ])
    # partial עם כפתורים
    partial_hits = _grep(r"video_file_controls", tpls)
    REPORT["templates"]["partial_controls_include"] = [str(p.relative_to(ROOT)) for p in partial_hits]

    # קובץ JS
    static_js = _find_candidates([
        "static/js/**/*.js",
        "admin_web/static/js/**/*.js",
    ])
    js_hits = _grep(r"video_file_controls\.js", static_js)
    REPORT["templates"]["js_controls"] = [str(p.relative_to(ROOT)) for p in js_hits]

def check_deps():
    # FFmpeg
    REPORT["deps"]["ffmpeg_in_path"] = bool(shutil.which("ffmpeg"))
    # Pillow אופציונלי לניתוח בהירות/מידות
    try:
        import PIL  # noqa
        REPORT["deps"]["Pillow"] = True
    except Exception:
        REPORT["deps"]["Pillow"] = False

def advise():
    # get_streamer & read_frame
    if not REPORT["files"]["get_streamer"]:
        REPORT["notes"].append("MISSING get_streamer(): מומלץ להשאיר סטרימר מרכזי app/ui/video.py שממנו כל המערכת קוראת.")
    if not REPORT["files"]["read_frame"]:
        REPORT["notes"].append("MISSING read_frame(): פונקציה שמחזירה (ok, jpeg_bytes) להזנת /video/stream.mjpg.")

    # endpoints
    if not REPORT["endpoints"]["/api/video/start_file"]:
        REPORT["notes"].append("MISSING /api/video/start_file: להוסיף blueprint קטן להפעלת קובץ כמצלמה (לא לגעת ב-/video/stream.mjpg).")
    if not REPORT["endpoints"]["/api/video/upload_and_play"]:
        REPORT["notes"].append("OPTIONAL /api/video/upload_and_play: מאפשר להעלות קובץ מהדשבורד ולהפעיל מיד.")
    if not REPORT["endpoints"]["/api/video/start_camera"]:
        REPORT["notes"].append("MISSING /api/video/start_camera: כפתור חזרה למצלמה.")

    # UI
    if not REPORT["templates"]["partial_controls_include"]:
        REPORT["notes"].append("UI: הוסף partial 'partials/video_file_controls.html' + include בעמוד הדשבורד.")
    if not REPORT["templates"]["js_controls"]:
        REPORT["notes"].append("UI: הוסף static/js/video_file_controls.js והטען אותו בעמוד.")

    # deps
    if not REPORT["deps"]["ffmpeg_in_path"]:
        REPORT["notes"].append("Install FFmpeg: חייב ffmpeg ב-PATH כדי להזרים וידאו כ-MJPEG.")
    if REPORT["deps"]["Pillow"] is False:
        REPORT["notes"].append("Optional: pillow לעיבוד בהירות/מידות ב-worker (לא חובה).")

def main():
    check_streamer()
    check_routes()
    check_templates()
    check_deps()
    advise()
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
