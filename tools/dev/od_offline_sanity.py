# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# od_offline_sanity.py — בדיקת "עשן" אופליין לזיהוי אובייקטים בלי OpenCV/YOLO
# -----------------------------------------------------------------------------
from __future__ import annotations
import sys, argparse, traceback
from pathlib import Path
from typing import Any, Dict
from types import SimpleNamespace

EXIT_OK = 0
EXIT_FAIL = 1

def _add_project_root() -> Path:
    here = Path(__file__).resolve()
    project_root = here.parents[2]  # tools/dev/ -> BodyPlus_XPro/
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return project_root

def _print_kv(title: str, mapping: Dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    for k, v in mapping.items():
        print(f"{k:>20}: {v}")

def _to_dict(obj: Any) -> Any:
    if isinstance(obj, SimpleNamespace):
        return {k: _to_dict(v) for k, v in vars(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        t = [_to_dict(v) for v in obj]
        return t if isinstance(obj, list) else tuple(t)
    return obj

def _to_ns(obj: Any) -> Any:
    """המרה רקורסיבית dict/list -> SimpleNamespace/list"""
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [ _to_ns(v) for v in obj ]
    if isinstance(obj, tuple):
        return tuple(_to_ns(v) for v in obj)
    return obj

def main() -> int:
    parser = argparse.ArgumentParser(description="Offline OD sanity (no camera/OpenCV)")
    parser.add_argument("--provider", default="devnull", help="detector provider override (default: devnull)")
    parser.add_argument("--yaml", default="core/object_detection/object_detection.yaml",
                        help="path to object detection YAML (relative to project root)")
    args = parser.parse_args()

    project_root = _add_project_root()
    yaml_path = (project_root / args.yaml).resolve()

    info = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "project_root": str(project_root),
        "yaml_path": str(yaml_path),
        "provider_override": args.provider,
    }
    _print_kv("OD Offline Sanity — Env", info)

    # 1) טעינת קונפיג
    try:
        from core.object_detection import config_loader
    except Exception:
        print("\n[FAIL] import core.object_detection.config_loader")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        cfg_raw = config_loader.load_object_detection_config(str(yaml_path))  # עשוי להיות SimpleNamespace
        cfg = _to_dict(cfg_raw)  # נעבוד כ-dict לשינויים
        print("\n[OK] YAML loaded")
    except Exception:
        print("\n[FAIL] YAML load")
        traceback.print_exc()
        return EXIT_FAIL

    # 2) Override לספק + כיבוי tracking כדי למנוע רעש
    try:
        if isinstance(cfg, dict) and "profiles" in cfg and "active_profile" in cfg:
            prof_name = cfg.get("active_profile") or "default"
            profiles = cfg.setdefault("profiles", {})
            profile = profiles.setdefault(prof_name, {})
            detector = profile.setdefault("detector", {})
            detector["provider"] = args.provider
            profile["tracking_enabled"] = False
            # תאימות: ודא ששדות בסיסיים קיימים כדי למנוע גישת מאפיינים חסרים
            detector.setdefault("threshold", 0.15)
            detector.setdefault("overlap", 0.5)
            detector.setdefault("max_objects", 50)
            detector.setdefault("imgsz", 640)
            print(f"[OK] provider forced -> {args.provider!r} (profile={prof_name})")
        else:
            cfg = {
                "active_profile": "default",
                "profiles": {
                    "default": {
                        "detector": {"provider": args.provider, "threshold": 0.15, "overlap": 0.5, "max_objects": 50, "imgsz": 640},
                        "tracking_enabled": False,
                    }
                }
            }
            print(f"[OK] built minimal cfg -> provider={args.provider!r}")
    except Exception:
        print("\n[FAIL] provider override")
        traceback.print_exc()
        return EXIT_FAIL

    # 3) המרה חזרה ל-Namespace כדי להתאים ל-DetectorService שמצפה ל-attributes
    cfg_ns = _to_ns(cfg)

    # 4) אתחול DetectorService
    try:
        from core.object_detection.detector_base import DetectorService
    except Exception:
        print("\n[FAIL] import DetectorService")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        service = None
        factory = getattr(DetectorService, "from_config", None)
        if callable(factory):
            service = factory(cfg_ns)
        else:
            service = DetectorService(cfg_ns)  # __init__ שמצפה ל-namespace עם .provider

        if service is None:
            print("\n[FAIL] DetectorService created as None")
            return EXIT_FAIL

        # איסוף נתונים בסיסיים
        details = {}
        for attr in ("provider", "threshold", "overlap", "max_objects", "imgsz"):
            details[attr] = getattr(service, attr, "<n/a>")
        _print_kv("DetectorService", details)

        print("\n[SUCCESS] DetectorService initialized without camera/OpenCV.")
    except Exception:
        print("\n[FAIL] DetectorService init")
        traceback.print_exc()
        return EXIT_FAIL
    finally:
        try:
            closer = getattr(service, "close", None)
            if callable(closer):
                closer()
        except Exception:
            pass

    return EXIT_OK

if __name__ == "__main__":
    raise SystemExit(main())
