# -*- coding: utf-8 -*-
"""
compat_check.py — בדיקת תאימות ספריות + YAML + Dockerfile (לוקאלי/ענן/Serverless)
-------------------------------------------------------------------------------
מה נבדק?
1) סביבת Python, מערכת, נתיב פרויקט.
2) ספריות: ultralytics, torch/vision (CPU), pillow, PyYAML, Flask, requests, mediapipe (אופציונלי).
3) cv2: אזהרה אם opencv-python (GUI) מותקן; דרישה להשאיר רק opencv-python-headless.
4) YAML של הזיהוי: active_profile, provider, imgsz, threshold/overlap, weights (קיים? יחסי?).
5) ENV: ENABLE_LOCAL_YOLO_WORKER / OD_YAML / DETECTOR_PROFILE.
6) requirements.txt: דגלים בעייתיים (opencv-python במקום headless, numpy>=2 עם ultralytics<9, חוסרים).
7) Dockerfile: בסיס מתאים (python:3.11-slim), התקנות נכונות (headless, ffmpeg), שימוש ב-ENV, EXPOSE/CMD.
8) בדיקת טעינת YOLO + משקלים (smoke test) ללא ריצה בפועל.

פלט:
- רשימת ✅/⚠️/❌ עם סיכום ברור ומה לתקן.
"""

from __future__ import annotations
import sys, os, platform, re, json
from pathlib import Path
from typing import Dict, Any, List, Optional

OK="✅"; WARN="⚠️"; BAD="❌"

def note(ok: bool, msg: str): print(f"{OK if ok else BAD} {msg}")
def warn(msg: str): print(f"{WARN} {msg}")

def read_text_safe(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

def find_pkg(name: str):
    try:
        import importlib
        m = importlib.import_module(name)
        ver = getattr(m, "__version__", "?")
        return True, ver, m
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}", None

def boolish(x) -> bool:
    return str(x).strip().lower() in ("1","true","yes","on")

def parse_requirements(txt: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#"): continue
        # very rough parse pkg==ver / pkg>=ver / pkg
        m = re.match(r"([A-Za-z0-9_.\-]+)\s*([=<>!~]=\s*[^#\s]+)?", s)
        if m:
            pkg = m.group(1).lower()
            out[pkg] = s
    return out

def main() -> int:
    proj = Path(__file__).resolve().parents[2]  # tools/dev -> project root
    print("\n== Environment ==")
    print(f"{'python:':>14} {sys.version.split()[0]}")
    print(f"{'platform:':>14} {sys.platform} ({platform.system()})")
    print(f"{'project_root:':>14} {proj}")

    # --- 1) Packages ---
    print("\n== Packages ==")
    checks = {}
    for mod in ("ultralytics","torch","torchvision","PIL","yaml","flask","requests","mediapipe"):
        ok, ver, _ = find_pkg(mod if mod not in ("PIL","yaml") else {"PIL":"PIL","yaml":"yaml"}[mod])
        name = {"PIL":"pillow","yaml":"PyYAML"}.get(mod, mod)
        checks[name] = (ok, ver)
        if ok: note(True, f"{name} {ver}")
        else:  warn(f"{name} missing ({ver})")

    # OpenCV status
    ocv_gui, ocv_headless = False, False
    try:
        import pkgutil
        ocv_gui = pkgutil.find_loader("cv2") is not None
    except Exception:
        ocv_gui = False
    # נסה לזהות headless באמצעות pip metadata
    try:
        import subprocess, json as _json
        out = subprocess.check_output([sys.executable,"-m","pip","list","--format","json"], text=True)
        pkgs = {p["name"].lower(): p["version"] for p in _json.loads(out)}
        ocv_headless = "opencv-python-headless" in pkgs
        ocv_gui = ocv_gui and ("opencv-python" in pkgs)  # דיוק טוב יותר
        if "opencv-python" in pkgs and ocv_headless:
            warn("מותקנים יחד opencv-python ו-opencv-python-headless — מומלץ להסיר את opencv-python (GUI).")
        if "opencv-python" in pkgs and "opencv-python-headless" not in pkgs:
            warn("מותקן opencv-python (GUI) ללא headless — בענן זה עלול לשבור. התקן opencv-python-headless והסר opencv-python.")
        if "opencv-python-headless" in pkgs:
            note(True, f"opencv-python-headless {pkgs['opencv-python-headless']}")
    except Exception:
        pass

    # Torch CPU mode
    if checks["torch"][0]:
        try:
            import torch
            note(not torch.cuda.is_available(), f"torch cuda_available={torch.cuda.is_available()} (לענן/Serverless CPU רצוי False)")
        except Exception as e:
            warn(f"torch check failed ({e})")

    # --- 2) OD ENV ---
    print("\n== OD ENV ==")
    env = {
        "ENABLE_LOCAL_YOLO_WORKER": os.getenv("ENABLE_LOCAL_YOLO_WORKER"),
        "OD_YAML": os.getenv("OD_YAML"),
        "DETECTOR_PROFILE": os.getenv("DETECTOR_PROFILE"),
    }
    for k,v in env.items():
        if v: note(True, f"{k}={v}")
        else: warn(f"{k} not set")

    # --- 3) YAML ---
    print("\n== OD YAML ==")
    ypath = Path(env.get("OD_YAML") or (proj/"core/object_detection/object_detection.yaml"))
    if not ypath.exists():
        note(False, f"YAML not found: {ypath}")
        return 1
    note(True, f"YAML: {ypath}")

    data: Dict[str, Any] = {}
    if checks["PyYAML"][0]:
        import yaml
        try:
            data = yaml.safe_load(ypath.read_text(encoding="utf-8", errors="ignore")) or {}
        except Exception as e:
            note(False, f"YAML parse error: {e}")
            return 1
    else:
        note(False, "PyYAML חסר — לא ניתן לפרסר YAML")
        return 1

    act = env.get("DETECTOR_PROFILE") or data.get("active_profile")
    if not act:
        note(False, "active_profile לא הוגדר (ENV או YAML)")
        return 1
    note(True, f"active_profile={act}")

    prof = (data.get("profiles", {}) or {}).get(act, {})
    if not prof:
        note(False, f"פרופיל '{act}' לא נמצא ב-YAML")
        return 1

    det = prof.get("detector", {}) or {}
    provider = det.get("provider") or "unknown"
    imgsz = det.get("imgsz", 640)
    thr = det.get("threshold", 0.15)
    iou = det.get("overlap", 0.50)
    note(True, f"provider={provider} imgsz={imgsz} thr={thr} iou={iou}")

    weights = det.get("weights") or det.get("weights_path")
    if not weights:
        note(False, "weights לא הוגדרו בפרופיל")
    # ודא נתיב יחסי (לטובת Docker/ענן)
    if ":" in str(weights) and "\\" in str(weights):
        warn(f"weights נראה כמו נתיב Windows: {weights} — מומלץ להפוך ליחסי (core/object_detection/models/best.pt)")
    abs_weights = (ypath.parent / Path(weights)).resolve() if not Path(weights).is_absolute() else Path(weights)
    if abs_weights.exists():
        note(True, f"weights found: {abs_weights}")
    else:
        note(False, f"weights not found: {abs_weights}")

    # --- 4) requirements.txt ---
    print("\n== requirements.txt ==")
    req_p = proj / "requirements.txt"
    if req_p.exists():
        req_txt = read_text_safe(req_p) or ""
        reqs = parse_requirements(req_txt)
        if "opencv-python" in reqs and "opencv-python-headless" not in reqs:
            warn("requirements.txt כולל opencv-python (GUI) ללא headless — לשנות ל-opencv-python-headless בלבד.")
        if "ultralytics" in reqs and "numpy" in reqs:
            # בדיקה גסה: אולטרהליטיקס 8.x מעדיף numpy<2
            if "numpy>=" in reqs["numpy"] and any(v in reqs["numpy"] for v in (">=2", "==2", "~=2")):
                warn("requirements.txt מציין numpy 2.x לצד ultralytics 8.x — זה עלול לשבור. העדף numpy<2.0.")
        needed = ["ultralytics","opencv-python-headless","pillow","PyYAML","flask","requests"]
        missing = [n for n in needed if n not in reqs]
        if missing:
            warn(f"requirements.txt חסר חבילות בסיס: {', '.join(missing)}")
        note(True, "requirements.txt נסרק")
    else:
        warn("requirements.txt לא נמצא — מומלץ להוסיף אחד עקבי עם Dockerfile.")

    # --- 5) Dockerfile ---
    print("\n== Dockerfile ==")
    df_p = proj / "Dockerfile"
    if not df_p.exists():
        warn("Dockerfile לא נמצא — אדפיס תבנית מומלצת בסוף.")
        docker_txt = None
    else:
        docker_txt = read_text_safe(df_p)
        if docker_txt is None:
            warn("Dockerfile לא קריא (הרשאות/קידוד).")
        else:
            base_ok = bool(re.search(r"FROM\s+python:3\.11.*slim", docker_txt))
            note(base_ok, "FROM python:3.11-slim (מומלץ)")
            if not base_ok and "FROM" in docker_txt:
                warn("בסיס Docker שונה — ודא תאימות (python 3.11-slim מומלץ).")

            if re.search(r"opencv-python(?!-headless)", docker_txt, re.IGNORECASE):
                warn("Dockerfile מתקין opencv-python (GUI) — החלף ל-opencv-python-headless.")

            if not re.search(r"opencv-python-headless", docker_txt, re.IGNORECASE):
                warn("Dockerfile לא מתקין opencv-python-headless — נדרש לאולטרהליטיקס בענן.")

            if not re.search(r"ultralytics", docker_txt, re.IGNORECASE):
                warn("Dockerfile לא מתקין ultralytics — הוסף pip install ultralytics.")

            if not re.search(r"ffmpeg", docker_txt, re.IGNORECASE):
                warn("Dockerfile לא מתקין ffmpeg — נחוץ ל-upload-video דרך FFmpeg (אם משתמש).")

            if not re.search(r"EXPOSE\s+5000", docker_txt):
                warn("Dockerfile חסר EXPOSE 5000 (או הפורט שבו Flask/Gunicorn מאזין).")

            cmd_ok = bool(re.search(r'CMD\s+\[.*(gunicorn|python).*]', docker_txt, re.IGNORECASE))
            note(cmd_ok, "CMD להרצת השרת קיים (gunicorn/python)")
            if not cmd_ok:
                warn("Dockerfile חסר CMD שמריץ את האפליקציה (למשל gunicorn app.main:app).")

    # --- 6) YOLO smoke test ---
    print("\n== YOLO Smoke Test ==")
    if not checks["ultralytics"][0]:
        warn("ultralytics לא מותקן — pip install 'ultralytics==8.3.*'")
    else:
        try:
            from ultralytics import YOLO
            if abs_weights.exists():
                YOLO(str(abs_weights))  # טעינה בלבד
                note(True, "YOLO(weights) load OK")
            else:
                warn("YOLO נטען, אך weights לא נמצאו — תאתר/תעתיק את best.pt")
        except Exception as e:
            note(False, f"YOLO load failed: {e}")

    # --- Summary ---
    print("\n== Summary ==")
    problems = []
    if not checks["ultralytics"][0]: problems.append("ultralytics חסר")
    if ocv_gui and not ocv_headless: problems.append("opencv-python (GUI) מותקן בלי headless")
    if not abs_weights.exists(): problems.append("weights לא נמצאו")
    if docker_txt is None: problems.append("Dockerfile חסר/לא קריא")
    if "DETECTOR_PROFILE" not in os.environ and not data.get("active_profile"): problems.append("active_profile חסר (ENV/YAML)")

    if problems:
        print(BAD, "יש פריטים לתיקון:\n - " + "\n - ".join(problems))
    else:
        print(OK, "נראה תקין לפריסה לוקאלית וענן (Serverless) עם Dockerheadless.")

    # --- Suggest Dockerfile template if missing/bad ---
    if docker_txt is None:
        print("\n-- Dockerfile (תבנית מומלצת) --")
        print(r"""
FROM python:3.11-slim

# System deps (ffmpeg לצורך upload-video), build basics
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg git curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

# התקנות פייתון — ראשית עדכון pip
RUN python -m pip install --upgrade pip setuptools wheel

# ספריות: רק headless
RUN pip install --no-cache-dir \
    "opencv-python-headless>=4.11,<5" \
    "ultralytics==8.3.*" \
    pillow PyYAML flask requests gunicorn

# (אם יש requirements.txt משלך, אפשר להחליף ל:
# COPY requirements.txt /app/
# RUN pip install --no-cache-dir -r requirements.txt
# ודא שבתוך requirements יש opencv-python-headless ולא opencv-python)

# ENV ל-OD (אפשר גם בזמן ריצה)
ENV ENABLE_LOCAL_YOLO_WORKER=0 \
    OD_YAML=/app/core/object_detection/object_detection.yaml \
    DETECTOR_PROFILE=yolov8_cpu_640

EXPOSE 5000

# Gunicorn (או python app/main.py אם תרצה)
# נניח שהאפליקציה היא Flask בשם app.main:app
CMD ["gunicorn","-w","2","-b","0.0.0.0:5000","app.main:app","--timeout","120"]
""")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
