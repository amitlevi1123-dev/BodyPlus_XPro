# -*- coding: utf-8 -*-
"""
בדיקה מערכתית מלאה – BodyPlus_XPro (ללא OpenCV)
------------------------------------------------
בודק: מבנה תיקיות, ייבוא מודולים, קבצי קונפיג, ספריות Python, Flask app/routes,
פורט פנוי, חומרה (Torch/ONNX), ויוצר דו"ח JSON מסכם.

הרצה:
    python tools/tests/test_fullstack_envcheck.py
"""

import os
import sys
import json
import time
import socket
import importlib
import platform
import traceback
from pathlib import Path
from typing import Any, Dict, List

LINE = "-" * 90
REPORT: Dict[str, Any] = {"env": {}, "dirs": {}, "modules": {}, "api": {}, "files": {}, "libs": {}, "system": {}, "hardware": {}}

# -------------------------------------------------------------
# איתור שורש הפרויקט (חי)
# -------------------------------------------------------------
_here = Path(__file__).resolve()
candidates = [_here.parents[i] for i in range(1, 6)]
ROOT = None
for c in candidates:
    if all((c / d).exists() for d in ["core", "app", "admin_web"]):
        ROOT = c
        break
if ROOT is None:
    ROOT = _here.parents[1]
sys.path.insert(0, str(ROOT))

def mark(section: str, name: str, ok: bool, note: str = ""):
    REPORT.setdefault(section, {})[name] = {"ok": ok, "note": note}
    icon = "✅" if ok else "❌"
    print(f"{icon} {section:<12} | {name:<35} | {note}")

def warn(section: str, name: str, note: str):
    REPORT.setdefault(section, {})[name] = {"ok": None, "note": note}
    print(f"⚠️ {section:<12} | {name:<35} | {note}")

def divider(title: str):
    print("\n" + LINE)
    print(f"🔹 {title}")
    print(LINE)

# ------------------ שלב 1: מידע סביבתי ------------------
def check_env():
    divider("מידע על סביבת עבודה")
    info = {
        "Python": sys.version.split()[0],
        "Platform": platform.platform(),
        "Machine": platform.machine(),
        "CPU": platform.processor(),
        "WorkingDir": str(ROOT),
        "Time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "Venv": sys.prefix,
    }
    REPORT["env"] = info
    for k, v in info.items():
        print(f"   {k:<12}: {v}")
    if "venv" not in sys.prefix.lower():
        warn("env", "VirtualEnv", "לא רץ מתוך virtualenv — מומלץ להפעיל סביבה וירטואלית.")

# ------------------ שלב 2: תיקיות ------------------
def check_directories():
    divider("בדיקת תיקיות עיקריות")
    expected = ["core", "app", "admin_web", "exercise_engine", "exercise_library", "tools"]
    for d in expected:
        p = ROOT / d
        mark("dirs", d, p.exists(), f"Exists={p.exists()} Path={p}")

# ------------------ שלב 3: ייבוא מודולים ------------------
def check_module_imports():
    divider("ייבוא מודולים עיקריים")
    modules = [
        "core.logs",
        "core.payload",
        "app.ui.video",
        "app.ui.video_metrics_worker",
        "admin_web.server",
        "admin_web.routes_video",
        "exercise_engine.runtime.runtime",
        "exercise_engine.runtime.engine_settings",
    ]
    for m in modules:
        try:
            importlib.import_module(m)
            mark("modules", m, True)
        except Exception as e:
            msg = str(e).split("\n")[0]
            mark("modules", m, False, msg)

# ------------------ שלב 4: קבצי קונפיג ------------------
def check_config_files():
    divider("בדיקת קבצי קונפיג (YAML/JSON)")
    yamls = [
        "core/configs/object_detection.yaml",
        "core/configs/phrases.yaml",
    ]
    for y in yamls:
        p = ROOT / y
        mark("files", y, p.exists(), f"Exists={p.exists()}")
    ex_lib = ROOT / "exercise_library"
    all_yamls = list(ex_lib.rglob("*.yaml")) if ex_lib.exists() else []
    if all_yamls:
        mark("files", "exercise_library_yamls", True, f"{len(all_yamls)} YAML found")
    else:
        warn("files", "exercise_library_yamls", "לא נמצאו קבצי תרגילים בספריית exercise_library")

# ------------------ שלב 5: ספריות Python ------------------
def check_libraries_versions():
    divider("בדיקת ספריות Python")
    libs = ["flask", "mediapipe", "onnxruntime", "torch", "numpy", "pandas", "requests"]
    for lib in libs:
        try:
            mod = importlib.import_module(lib.replace("-", "_"))
            ver = getattr(mod, "__version__", "?")
            REPORT["libs"][lib] = {"ok": True, "note": ver}
            print(f"✅ libs         | {lib:<35} | {ver}")
        except Exception as e:
            REPORT["libs"][lib] = {"ok": False, "note": str(e).split("\n")[0]}
            print(f"❌ libs         | {lib:<35} | {str(e).splitlines()[0]}")

# ------------------ שלב 6: Flask app + routes + /payload ------------------
def check_flask_routes():
    divider("בדיקת Flask / routes / payload")
    try:
        from admin_web.server import create_app
        app = create_app()
        routes = sorted([r.rule for r in app.url_map.iter_rules()])
        must_have = ["/", "/payload", "/api/metrics", "/api/diagnostics", "/healthz"]
        missing = [r for r in must_have if r not in routes]
        mark("api", "total_routes", True, f"{len(routes)} routes detected")
        if missing:
            warn("api", "missing_routes", f"Missing: {missing}")
        else:
            mark("api", "routes_complete", True, "All essential routes OK")
        # /payload
        with app.test_client() as c:
            r = c.get("/payload")
            ok = (r.status_code == 200)
            try:
                j = r.get_json(force=True)
                keys = list(j.keys())[:6]
            except Exception:
                j, keys = {}, []
            mark("api", "payload_response", ok, f"Status={r.status_code} Keys={keys}")
            if ok and "payload_version" not in j:
                warn("api", "payload_version_missing", "הוסף payload_version לתגובה")
    except Exception as e:
        mark("api", "flask_init", False, str(e).split("\n")[0])

# ------------------ שלב 7: פורטים פנויים ------------------
def check_ports():
    divider("בדיקת פורטים פנויים (5000 / 8080 / 80)")
    ports = [5000, 8080, 80]
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", p))
            mark("system", f"port_{p}", True, "Free")
        except OSError:
            warn("system", f"port_{p}", "תפוס – ייתכן שתהליך Flask/Gunicorn כבר רץ")
        finally:
            s.close()

# ------------------ שלב 8: חומרה (Torch/ONNX) ------------------
def check_hardware():
    divider("בדיקת חומרה (GPU / CPU)")
    # Torch
    try:
        import torch
        gpu = torch.cuda.is_available()
        devs = torch.cuda.device_count()
        mark("hardware", "torch_cuda", gpu, f"{devs} device(s)" if gpu else "CPU only")
    except Exception as e:
        warn("hardware", "torch_cuda", f"לא זמין/לא מותקן: {e}")
    # ONNX
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        mark("hardware", "onnx_providers", True, f"{providers}")
    except Exception as e:
        warn("hardware", "onnx_providers", f"לא נטען: {e}")

# ------------------ שלב 9: סיכום + כתיבת דו"ח ------------------
def summarize():
    divider("סיכום כולל")
    total = 0
    fails = 0
    warns = 0
    for section, data in REPORT.items():
        if not isinstance(data, dict):
            continue
        for name, s in data.items():
            if not isinstance(s, dict):
                continue
            if "ok" in s:
                total += 1
                if s["ok"] is False:
                    fails += 1
                elif s["ok"] is None:
                    warns += 1
    oks = total - fails - warns
    print(f"✅ תקין: {oks}   ⚠️ אזהרות: {warns}   ❌ כשלים: {fails}   (סה\"כ {total})")

    if fails or warns:
        print("\n🔧 הצעות לתיקון:")
        for section, data in REPORT.items():
            if not isinstance(data, dict):
                continue
            for name, s in data.items():
                if isinstance(s, dict) and s.get("ok") in [False, None]:
                    icon = "❌" if s.get("ok") is False else "⚠️"
                    print(f"  {icon} [{section}] {name}: {s.get('note','')}")

    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    out = ROOT / f"tools/tests/_report_fullstack_{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print(f"\n📁 דו\"ח נשמר: {out}")
    print(LINE)
    print("סיום בדיקה ✅")

# ------------------ Main ------------------
if __name__ == "__main__":
    print(LINE)
    print("🚀 התחלת בדיקה מערכתית מלאה — BodyPlus_XPro")
    print(LINE)
    try:
        check_env()
        check_directories()
        check_module_imports()
        check_config_files()
        check_libraries_versions()
        check_flask_routes()
        check_ports()
        check_hardware()
    except Exception:
        traceback.print_exc()
    summarize()
