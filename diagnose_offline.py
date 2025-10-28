# diagnose_offline.py
import os, sys, importlib, subprocess, time, socket, platform
from pathlib import Path

BASE = Path(__file__).resolve().parent

def check_file(path: str):
    f = BASE / path
    return f.exists(), str(f)

def check_import(module_name: str):
    try:
        importlib.import_module(module_name)
        return True
    except Exception as e:
        return False, str(e)

def check_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def print_header(title):
    print(f"\n{'=' * 10} {title} {'=' * 10}")

def status(ok, label, err=None):
    mark = "✅" if ok else "❌"
    print(f"{mark} {label}")
    if not ok and err:
        print(f"   ↳ {err}")

print_header("🔍 סביבה כללית")
status(True, f"Python version: {platform.python_version()}")
status(True, f"Platform: {platform.system()}")

print_header("📦 קבצים קריטיים")
for fname in ["main.py", "requirements.txt", "Dockerfile", "core", "admin_web"]:
    ok, path = check_file(fname)
    status(ok, f"{fname} קיים", None if ok else f"לא נמצא בנתיב: {path}")

print_header("📚 בדיקות מודולים (pip)")
for mod in ["flask", "requests", "cv2", "mediapipe", "core.kinematics"]:
    ok = check_import(mod)
    status(ok if isinstance(ok, bool) else False, f"מודול: {mod}", None if ok is True else ok[1])

print_header("🌐 בדיקת פורטים")
port = int(os.getenv("PORT", "5000"))
in_use = check_port_in_use(port)
status(not in_use, f"פורט {port} פנוי", "כבר בשימוש" if in_use else None)

print_header("🔄 בדיקת Flask App")
try:
    from main import app
    test_client = app.test_client()
    resp = test_client.get("/health")
    status(resp.status_code == 200, "/health מחזיר 200", f"Status={resp.status_code}")
except Exception as e:
    status(False, "Flask לא נטען כראוי מ־main.py", str(e))

print_header("🎥 בדיקת סטרימר")
try:
    from app.ui.video import get_streamer
    s = get_streamer()
    ok = hasattr(s, "read_frame")
    status(ok, "get_streamer() זמין", None if ok else "לא מחזיר אובייקט מתאים")
except Exception as e:
    status(False, "קריאת סטרימר נכשלה", str(e))

print_header("🧠 בדיקת MediaPipe")
try:
    from core.mediapipe_runner import MediaPipeRunner
    mpr = MediaPipeRunner(enable_pose=True, enable_hands=True)
    status(True, "MediaPipeRunner נוצר")
    mpr.release()
except Exception as e:
    status(False, "MediaPipeRunner שגיאה", str(e))

print_header("📦 Object Detection")
try:
    from core.object_detection.engine import ObjectDetectionEngine
    od = ObjectDetectionEngine.from_yaml("core/object_detection/object_detection.yaml")
    status(True, "Object Detection נטען")
except Exception as e:
    status(False, "Object Detection כשל", str(e))

print_header("🧪 בדיקת הרצה תחת Docker")
inside_docker = Path("/.dockerenv").exists()
status(inside_docker, "הרצה תחת Docker", None if inside_docker else "נראה שאתה לא בתוך קונטיינר")

print_header("🎉 סיום")
print("אם כל השורות ✅ — הכל מוכן להרצה.")

