# -*- coding: utf-8 -*-
"""
od_env_check.py — בדיקת סביבה נקייה ל-YOLO בענן/לוקאלי (בלי OpenCV)
-------------------------------------------------------------------
מה הוא בודק?
1) גרסת פייתון ופלטפורמה
2) חבילות: ultralytics, torch/vision/audio (CPU), pillow, PyYAML
3) שאין cv2 (אם יש — אזהרה להסרה)
4) משתני סביבה ל-OD: ENABLE_LOCAL_YOLO_WORKER, OD_YAML, DETECTOR_PROFILE
5) קובץ YAML: active_profile, provider, imgsz, threshold/overlap, weights (יחסי? קיים?)
6) טעינת Ultralytics + משקלים (אם קיימים) — בדיקת smoke מהירה (ללא ריצה)
"""

from __future__ import annotations
import sys, os, platform, json
from pathlib import Path
from typing import Any, Dict

OK="✅"; BAD="❌"; WARN="⚠️"

def pfx(ok: bool, msg: str) -> None:
    print(f"{OK if ok else BAD} {msg}")

def pfx_warn(msg: str) -> None:
    print(f"{WARN} {msg}")

def _bool(x: Any) -> bool:
    try:
        return str(x).strip().lower() in ("1","true","yes","on")
    except Exception:
        return False

def main() -> int:
    # 0) env basics
    proj = Path(__file__).resolve().parents[2]  # BodyPlus_XPro root (tools/dev/..)
    print("\n== OD Env Check ==")
    print(f"{'python:':>16} {sys.version.split()[0]}")
    print(f"{'platform:':>16} {sys.platform} ({platform.system()})")
    print(f"{'project_root:':>16} {proj}")

    # 1) packages
    print("\n== Packages ==")
    have = {}
    def chk(mod: str, alias: str|None=None):
        name = alias or mod
        try:
            m = __import__(mod)
            ver = getattr(m, "__version__", "?")
            have[name] = (True, ver)
            pfx(True, f"{name} {ver}")
            return m
        except Exception as e:
            have[name] = (False, None)
            pfx(False, f"{name} missing ({e.__class__.__name__})")
            return None

    ul = chk("ultralytics")
    th = chk("torch")
    tv = chk("torchvision")
    ta = chk("torchaudio")
    pil = chk("PIL", "pillow")
    ym = chk("yaml", "PyYAML")

    # cv2 should NOT be installed
    try:
        import cv2  # noqa
        pfx_warn("cv2 נמצא מותקן — מומלץ להסיר: pip uninstall -y opencv-python opencv-python-headless opencv-contrib-python")
    except Exception:
        pfx(True, "אין cv2 (טוב)")

    # Torch CPU check (לא חובה, אבל מועיל)
    if th:
        try:
            import torch
            cuda = bool(torch.cuda.is_available())
            mps  = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())  # mac
            pfx(not cuda, f"torch cuda_available={cuda} (לענן CPU רצוי False)")
            if mps:
                pfx_warn("MPS זמין (Mac) — לא בעיה, רק לידיעה")
        except Exception as e:
            pfx(False, f"torch check failed ({e})")

    # 2) ENV for OD
    print("\n== OD ENV ==")
    env = {
        "ENABLE_LOCAL_YOLO_WORKER": os.getenv("ENABLE_LOCAL_YOLO_WORKER"),
        "OD_YAML": os.getenv("OD_YAML"),
        "DETECTOR_PROFILE": os.getenv("DETECTOR_PROFILE"),
    }
    for k,v in env.items():
        if v:
            pfx(True, f"{k}={v}")
        else:
            pfx_warn(f"{k} not set")

    # 3) YAML resolve
    print("\n== YAML ==")
    od_yaml = env.get("OD_YAML") or str(proj / "core" / "object_detection" / "object_detection.yaml")
    ypath = Path(od_yaml)
    if not ypath.exists():
        pfx(False, f"YAML not found: {ypath}")
        return 1
    pfx(True, f"YAML: {ypath}")

    data: Dict[str, Any] = {}
    if ym:
        import yaml
        data = yaml.safe_load(ypath.read_text(encoding="utf-8", errors="ignore")) or {}
    else:
        pfx(False, "PyYAML חסר — לא ניתן לפרסר YAML")
        return 1

    act = env.get("DETECTOR_PROFILE") or data.get("active_profile")
    if not act:
        pfx(False, "active_profile לא הוגדר (ב-YAML או ב-ENV)")
        return 1
    pfx(True, f"active_profile={act}")

    prof = (data.get("profiles", {}) or {}).get(act, {})
    if not prof:
        pfx(False, f"פרופיל '{act}' לא נמצא ב-YAML")
        return 1

    det = prof.get("detector", {}) or {}
    provider = det.get("provider") or "unknown"
    imgsz = det.get("imgsz", 640)
    thr = det.get("threshold", 0.15)
    iou = det.get("overlap", 0.50)
    pfx(True, f"provider={provider} imgsz={imgsz} thr={thr} iou={iou}")

    # weights: חייב להיות מסלול יחסי בקונטיינר/פרויקט (לא C:\)
    weights = det.get("weights") or det.get("weights_path")
    if not weights:
        pfx(False, "weights לא הוגדרו בפרופיל")
        return 1

    if ":" in str(weights) and "\\" in str(weights):
        pfx_warn(f"weights נראים כמו נתיב Windows: {weights} — מומלץ להפוך ליחסי (למשל core/object_detection/models/best.pt)")

    # resolve to absolute based on YAML dir
    abs_weights = (ypath.parent / Path(weights)).resolve() if not Path(weights).is_absolute() else Path(weights)
    if abs_weights.exists():
        pfx(True, f"weights found: {abs_weights}")
    else:
        pfx(False, f"weights not found: {abs_weights}")

    # 4) Ultralytics smoke test (טעינת מודל; בלי ריצה)
    print("\n== Ultralytics Smoke Test ==")
    if not ul:
        pfx(False, "ultralytics חסר — התקן: pip install 'ultralytics==8.3.*'")
        return 1
    try:
        from ultralytics import YOLO
        m = YOLO(str(abs_weights)) if abs_weights.exists() else YOLO  # אם חסר קובץ — לפחות שהייבוא יעבוד
        if abs_weights.exists():
            pfx(True, "YOLO(weights) load OK")
        else:
            pfx_warn("YOLO נטען, אך weights לא נמצאו — יש להשלים קובץ משקלים")
    except Exception as e:
        pfx(False, f"YOLO load failed ({e.__class__.__name__}: {e})")
        return 1

    # Summary
    print("\n== Summary ==")
    ok = (
        have.get("ultralytics", (False,))[0] and
        have.get("pillow", (False,))[0] and
        have.get("PyYAML", (False,))[0] and
        (abs_weights.exists())
    )
    if ok:
        pfx(True, "הסביבה מוכנה להרצה (ingest מהדפדפן + YOLO CPU)")
        return 0
    else:
        pfx_warn("יש פריטים לטיפול (ראה סימונים למעלה).")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
