# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# od_healthcheck.py — בדיקת בריאות אופליין ל-OD ללא OpenCV/YOLO
# -----------------------------------------------------------------------------
# מה הקובץ עושה?
# 1) מוסיף את שורש הפרויקט ל-PYTHONPATH (חסין נתיב).
# 2) טוען YAML של זיהוי אובייקטים, כופה provider=devnull, מכבה tracking.
# 3) מאתחל DetectorService כ-Namespace (לא dict), בלי מצלמה ובלי OpenCV.
# 4) מדפיס PASS/FAIL עם סיבת כשל ברורה + קוד יציאה (0/1).
# שימוש:
#   .\.venv\Scripts\python.exe tools\dev\od_healthcheck.py
# -----------------------------------------------------------------------------
from __future__ import annotations
import sys, traceback
from pathlib import Path
from types import SimpleNamespace

EXIT_OK = 0
EXIT_FAIL = 1

def add_root() -> Path:
    here = Path(__file__).resolve()
    root = here.parents[2]  # tools/dev -> BodyPlus_XPro
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root

def to_dict(obj):
    if isinstance(obj, SimpleNamespace):
        return {k: to_dict(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        t = [to_dict(v) for v in obj]
        return t if isinstance(obj, list) else tuple(t)
    return obj

def to_ns(obj):
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [to_ns(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(to_ns(v) for v in obj)
    return obj

def main() -> int:
    root = add_root()
    yaml_path = (root / "core/object_detection/object_detection.yaml").resolve()
    print(f"[HC] Project root: {root}")
    print(f"[HC] YAML path   : {yaml_path}")
    print(f"[HC] Python      : {sys.version.split()[0]} | Platform: {sys.platform}")

    try:
        from core.object_detection import config_loader
    except Exception:
        print("[FAIL] import config_loader")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        cfg_raw = config_loader.load_object_detection_config(str(yaml_path))
        cfg = to_dict(cfg_raw)
        print("[OK] YAML loaded")
    except Exception:
        print("[FAIL] YAML load")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        prof = cfg.get("active_profile") or "default"
        profiles = cfg.setdefault("profiles", {})
        profile = profiles.setdefault(prof, {})
        det = profile.setdefault("detector", {})
        det.setdefault("threshold", 0.15)
        det.setdefault("overlap", 0.5)
        det.setdefault("max_objects", 50)
        det.setdefault("imgsz", 640)
        det["provider"] = "devnull"   # ללא OpenCV/YOLO
        profile["tracking_enabled"] = False
        print(f"[OK] provider forced -> devnull (profile={prof})")
    except Exception:
        print("[FAIL] provider override")
        traceback.print_exc()
        return EXIT_FAIL

    cfg_ns = to_ns(cfg)

    try:
        from core.object_detection.detector_base import DetectorService
    except Exception:
        print("[FAIL] import DetectorService")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        factory = getattr(DetectorService, "from_config", None)
        service = factory(cfg_ns) if callable(factory) else DetectorService(cfg_ns)
        if service is None:
            print("[FAIL] DetectorService is None")
            return EXIT_FAIL

        # איסוף פרטים בטוחים
        attrs = {k: getattr(service, k, "<n/a>") for k in ("provider", "threshold", "overlap", "max_objects", "imgsz")}
        print("[OK] DetectorService init")
        for k, v in attrs.items():
            print(f"    {k:>12}: {v}")

        closer = getattr(service, "close", None)
        if callable(closer):
            closer()
        print("[PASS] OD offline healthcheck succeeded.")
        return EXIT_OK
    except Exception:
        print("[FAIL] DetectorService init")
        traceback.print_exc()
        return EXIT_FAIL

if __name__ == "__main__":
    raise SystemExit(main())
