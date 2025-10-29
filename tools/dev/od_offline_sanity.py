# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# od_offline_sanity.py — בדיקת "עשן" אופליין לזיהוי אובייקטים בלי OpenCV/YOLO
# -----------------------------------------------------------------------------
from __future__ import annotations
import sys, argparse, traceback
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Dict, Tuple

EXIT_OK = 0
EXIT_FAIL = 1

# ---------- Utils ----------
def _add_project_root() -> Path:
    here = Path(__file__).resolve()
    project_root = here.parents[2]  # tools/dev/ -> BodyPlus_XPro/
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return project_root

def _is_ns(x: Any) -> bool:
    return isinstance(x, SimpleNamespace)

def _ns_get(ns: SimpleNamespace, name: str, default=None):
    return getattr(ns, name, default)

def _ensure_detector_container(profile: Any) -> Tuple[Any, bool]:
    """
    מחזיר את אובייקט ה-detector (dict או SimpleNamespace).
    אם לא קיים — יוצר אחד ומחזיר (עם דגל created=True).
    """
    created = False
    if _is_ns(profile):
        det = getattr(profile, "detector", None)
        if det is None:
            det = SimpleNamespace()
            setattr(profile, "detector", det)
            created = True
        return det, created
    else:
        # dict
        det = profile.get("detector")
        if det is None:
            det = {}
            profile["detector"] = det
            created = True
        return det, created

def _set_provider(cfg: Any, provider: str) -> None:
    """
    עושה override ל-provider ל-devnull (או למה שביקשת) גם ב-NS וגם ב-dict.
    מכבה tracking לרעש מינימלי.
    אם אין מבנה — בונה מבנה מינימלי.
    """
    # SimpleNamespace path
    if _is_ns(cfg):
        profiles = _ns_get(cfg, "profiles")
        active = _ns_get(cfg, "active_profile")
        if profiles is not None and active and hasattr(profiles, active):
            profile = getattr(profiles, active)
            det, _ = _ensure_detector_container(profile)
            # set provider
            if _is_ns(det):
                setattr(det, "provider", provider)
                # ערכי ברירת מחדל מועילים
                if getattr(det, "threshold", None) is None:
                    setattr(det, "threshold", 0.15)
                if getattr(det, "max_objects", None) is None:
                    setattr(det, "max_objects", 50)
            else:
                det["provider"] = provider
                det.setdefault("threshold", 0.15)
                det.setdefault("max_objects", 50)
            # tracking off
            if _is_ns(profile):
                setattr(profile, "tracking_enabled", False)
            else:
                profile["tracking_enabled"] = False
            return
        # מבנה מינימלי ל-NS
        default = SimpleNamespace()
        default.detector = SimpleNamespace(provider=provider, threshold=0.15, max_objects=50)
        default.tracking_enabled = False
        cfg.active_profile = "default"
        # נגדיר profiles כ-NS עם אטריבוט בשם "default"
        holder = SimpleNamespace()
        setattr(holder, "default", default)
        cfg.profiles = holder
        return

    # dict path
    if isinstance(cfg, dict):
        if "profiles" in cfg and "active_profile" in cfg:
            prof_name = cfg.get("active_profile")
            profile = cfg["profiles"].get(prof_name, {})
            cfg["profiles"][prof_name] = profile  # ודא החזרה
            det, _ = _ensure_detector_container(profile)
            det["provider"] = provider
            det.setdefault("threshold", 0.15)
            det.setdefault("max_objects", 50)
            profile["tracking_enabled"] = False
            return
        # מבנה מינימלי ל-dict
        cfg.clear()
        cfg.update({
            "active_profile": "default",
            "profiles": {
                "default": {
                    "detector": {"provider": provider, "threshold": 0.15, "max_objects": 50},
                    "tracking_enabled": False
                }
            }
        })
        return

    # אם הגיע טיפוס לא צפוי
    raise TypeError(f"Unsupported config type: {type(cfg)}")

def _print_kv(title: str, mapping: Dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    for k, v in mapping.items():
        print(f"{k:>20}: {v}")

# ---------- Main ----------
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
        "provider_override": args.provider
    }
    _print_kv("OD Offline Sanity — Env", info)

    # 1) טעינת קונפיג
    try:
        from core.object_detection import config_loader
        cfg = config_loader.load_object_detection_config(str(yaml_path))
        print("\n[OK] YAML loaded")
    except Exception:
        print("\n[FAIL] YAML load")
        traceback.print_exc()
        return EXIT_FAIL

    # 2) נעילת ספק (NS או dict)
    try:
        _set_provider(cfg, args.provider)
        print(f"[OK] provider forced -> {args.provider!r}")
    except Exception:
        print("\n[FAIL] provider override")
        traceback.print_exc()
        return EXIT_FAIL

    # 3) אתחול השירות (ללא מצלמה)
    try:
        from core.object_detection.detector_base import DetectorService
    except Exception:
        print("\n[FAIL] import DetectorService")
        traceback.print_exc()
        return EXIT_FAIL

    try:
        # אם יש מפעל from_config — נעדיף
        factory = getattr(DetectorService, "from_config", None)
        service = factory(cfg) if callable(factory) else DetectorService(cfg)
        if service is None:
            print("\n[FAIL] DetectorService created as None")
            return EXIT_FAIL

        # אוסף פרטים לזיהוי
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
