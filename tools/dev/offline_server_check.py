# -*- coding: utf-8 -*-
"""
tools/dev/offline_server_check.py
בדיקת שרת אופליין (ללא מצלמה, ללא אינטרנט) עם Flask test_client.

מה הקובץ בודק?
1) ייבוא השרת ממספר נתיבים אפשריים (admin_web.server / app.main / server).
2) יצירת אפליקציית Flask (create_app או app קיים).
3) קיום ראוטים קריטיים: /healthz, /payload, /api/metrics, /video/stream.mjpg (אם יש).
4) קריאות מבחן: /healthz==200, /payload==JSON, /api/metrics==ok.
5) ודא שאין פתיחת מצלמה אוטומטית (בודק שה-ALLOW_CAMERA אינו "1" ואם כן – מזהיר).
6) מדפיס דוח מסכם: PASS/FAIL לכל בדיקה.

הרצה:
    python tools/dev/offline_server_check.py
"""

from __future__ import annotations
import os, sys, importlib, json, traceback
from typing import Optional, Tuple

# --- נוודא שהשורש בתקן import ---
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# --- תמיד ננטרל מצלמה בבדיקה אופליין ---
os.environ.setdefault("ALLOW_CAMERA", "0")
os.environ.setdefault("PORT", "5000")

CANDIDATES = [
    # (module_path, attr_hint)
    ("admin_web.server", "create_app"),
    ("app.main", "create_app"),
    ("admin_web.server", "app"),
    ("app.main", "app"),
    ("server", "create_app"),
    ("server", "app"),
]

def load_app() -> Tuple[object, str]:
    """
    מנסה לטעון את האפליקציה מכמה נתיבים.
    מחזיר (app, מקור_שנטען_ממנו)
    """
    last_err = None
    for mod, hint in CANDIDATES:
        try:
            m = importlib.import_module(mod)
            if hasattr(m, "create_app"):
                app = m.create_app()  # type: ignore
                return app, f"{mod}.create_app()"
            if hasattr(m, "app"):
                app = getattr(m, "app")
                # אם זה callable (factory), ננסה לקרוא
                if callable(app):
                    app = app()
                return app, f"{mod}.app"
        except Exception as e:
            last_err = e
    raise RuntimeError(f"לא הצלחתי לטעון אפליקציה מהנתיבים הידועים. אחרון: {last_err}")

def has_rule(app, path: str) -> bool:
    return any(r.rule == path for r in app.url_map.iter_rules())

def find_rule_contains(app, text: str) -> Optional[str]:
    for r in app.url_map.iter_rules():
        if text in r.rule:
            return r.rule
    return None

def test_request(client, path: str, expect_json: bool=False, ok_keys: Tuple[str,...]=()):
    try:
        resp = client.get(path)
        status = resp.status_code
        if status != 200:
            return False, f"HTTP {status}"
        if expect_json:
            try:
                data = resp.get_json(force=True, silent=False)
                if ok_keys:
                    for k in ok_keys:
                        if k not in data:
                            return False, f"JSON ok but missing key '{k}'"
                return True, "OK (JSON)"
            except Exception as e:
                return False, f"bad JSON: {e}"
        return True, "OK"
    except Exception as e:
        return False, f"EXC: {e}"

def main():
    results = []
    print("=== Offline Server Check ===")
    print(f"Project root: {ROOT}")
    print(f"ALLOW_CAMERA={os.getenv('ALLOW_CAMERA')}")
    print("Trying to load app...")

    try:
        app, src = load_app()
        results.append(("load_app", True, f"Loaded from {src}"))
    except Exception as e:
        print(traceback.format_exc())
        results.append(("load_app", False, f"Failed: {e}"))
        app = None

    if not app:
        print("\nSummary:")
        for name, ok, msg in results:
            print(f"- {name:20} : {'PASS' if ok else 'FAIL'}  — {msg}")
        sys.exit(1)

    # --- מיפוי ראוטים ---
    routes = sorted(str(r.rule) for r in app.url_map.iter_rules())
    print("\nDiscovered routes:")
    for r in routes:
        print("  ", r)

    # --- בדיקות קיום ראוטים ---
    must_have = ["/healthz", "/payload", "/api/metrics"]
    for path in must_have:
        ok = has_rule(app, path)
        results.append((f"route:{path}", ok, "exists" if ok else "missing"))

    # וידאו: ננסה למצוא מסלול עם stream.mjpg אם לא ידוע בדיוק
    video_rule = "/video/stream.mjpg" if has_rule(app, "/video/stream.mjpg") else find_rule_contains(app, "stream.mjpg")
    results.append(("route:/video/stream.mjpg", bool(video_rule), video_rule or "missing"))

    # --- בקשות מבחן ---
    client = app.test_client()

    ok, msg = test_request(client, "/healthz")
    results.append(("GET /healthz", ok, msg))

    ok, msg = test_request(client, "/payload", expect_json=True)
    results.append(("GET /payload", ok, msg))

    ok, msg = test_request(client, "/api/metrics", expect_json=True, ok_keys=("ok", "metrics"))
    results.append(("GET /api/metrics", ok, msg))

    # אם יש route לוידאו – לא ננסה באמת לצרוך סטרים, רק בדיקת HEAD/GET קצרה
    if video_rule:
        try:
            resp = client.get(video_rule)
            ok = resp.status_code in (200, 206)  # 206 לפעמים לסטרים
            ctype = resp.headers.get("Content-Type", "")
            hint = f"HTTP {resp.status_code}, Content-Type: {ctype}"
            results.append((f"GET {video_rule}", ok, hint))
        except Exception as e:
            results.append((f"GET {video_rule}", False, f"EXC: {e}"))

    # --- אזהרות מצלמה ---
    if os.getenv("ALLOW_CAMERA") == "1":
        results.append(("camera_policy", False, "ALLOW_CAMERA=1 (מומלץ 0 בענן)"))
    else:
        results.append(("camera_policy", True, "ALLOW_CAMERA=0 (טוב לבדיקה/ענן)"))

    # --- סיכום ---
    print("\nSummary:")
    failed = 0
    for name, ok, msg in results:
        line = f"- {name:20} : {'PASS' if ok else 'FAIL'}  — {msg}"
        print(line)
        if not ok:
            failed += 1

    print("\nResult:", "ALL GOOD ✅" if failed == 0 else f"{failed} checks failed ❌")
    sys.exit(0 if failed == 0 else 2)

if __name__ == "__main__":
    main()
