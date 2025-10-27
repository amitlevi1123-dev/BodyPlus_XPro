# tools/trace_videocapture.py
# -*- coding: utf-8 -*-
import os, sys, traceback
from pathlib import Path
import importlib.util

def install_tracer():
    try:
        import cv2  # type: ignore
    except Exception:
        print("[trace] cv2 not installed; nothing to trace")
        return

    orig = cv2.VideoCapture  # type: ignore[attr-defined]

    class VCTracer:
        def __init__(self, *a, **k):
            print("\n[TRACE] cv2.VideoCapture called with:", a, k)
            print("[TRACE] Stack:")
            for line in traceback.format_stack(limit=30):
                sys.stdout.write(line)
            sys.stdout.flush()
            self._cap = orig(*a, **k)
        def __getattr__(self, name):
            return getattr(self._cap, name)

    try:
        cv2.VideoCapture = VCTracer  # type: ignore[attr-defined]
        print("[trace] VideoCapture tracer installed")
    except Exception as e:
        print("[trace] failed to patch VideoCapture:", e)

def find_and_import_server():
    """
    מנסה לטעון את server.py ישירות לפי נתיב קובץ (גם אם import server נכשל).
    קורא create_app() אם קיימת.
    """
    root = Path(__file__).resolve().parents[1]  # .../BodyPlus_XPro
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # 1) נסה import server רגיל
    try:
        import server  # type: ignore
        return getattr(server, "create_app", None)
    except Exception as e:
        print("[trace] import server failed, will search file:", repr(e))

    # 2) חפש server.py בקודקוד הפרויקט
    server_py = root / "server.py"
    if not server_py.exists():
        # לעיתים server נמצא בשם אחר; נסה app/main.py
        alt_main = root / "app" / "main.py"
        if alt_main.exists():
            spec = importlib.util.spec_from_file_location("app_main_trace", str(alt_main))
            mod = importlib.util.module_from_spec(spec)  # type: ignore
            assert spec and spec.loader
            spec.loader.exec_module(mod)                 # type: ignore
            return getattr(mod, "create_app", None) or getattr(mod, "run", None)

        raise SystemExit("Could not find server.py; set FLASK_APP or adjust path")

    spec = importlib.util.spec_from_file_location("server_trace", str(server_py))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    assert spec and spec.loader
    spec.loader.exec_module(mod)                 # type: ignore
    return getattr(mod, "create_app", None)

def boot_app():
    # ליתר ביטחון, אל תפתח מצלמה אוטומטית בזמן הטרייס
    os.environ.setdefault("NO_CAMERA", "1")

    create = find_and_import_server()
    if create is None:
        raise SystemExit("server has no create_app().")
    app = create()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)

if __name__ == "__main__":
    install_tracer()
    boot_app()
