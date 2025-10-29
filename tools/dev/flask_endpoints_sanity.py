# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# flask_endpoints_sanity.py — בדיקת תקינות Flask Endpoints (ללא מצלמה)
# -----------------------------------------------------------------------------
# מה זה עושה?
# 1) טוען את השרת (admin_web.server:create_app)
# 2) משתמש ב-test_client כדי לקרוא לכל הראוטים הקריטיים:
#    /version, /healthz, /video/stream.mjpg, /video/stream_file.mjpg
# 3) מדפיס תוצאה ברורה (PASS/FAIL) לכל אחד.
# 4) לא פותח מצלמה, לא מעלה שום קובץ — רק בודק שהכל רשום ומחזיר קוד תקין.
# -----------------------------------------------------------------------------

from __future__ import annotations
import sys
from pathlib import Path

def _add_root() -> Path:
    here = Path(__file__).resolve()
    root = here.parents[2]  # tools/dev -> BodyPlus_XPro
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root

def _check(client, path: str) -> bool:
    """בודק ראוט אחד ומחזיר True/False לפי קוד התגובה"""
    try:
        resp = client.get(path)
        if resp.status_code == 200:
            print(f"✅ {path} → 200 OK")
            return True
        else:
            print(f"⚠️  {path} → {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ {path} → EXCEPTION: {e}")
        return False

def main() -> int:
    root = _add_root()
    print(f"[FlaskSanity] Root={root}")
    print(f"[FlaskSanity] Python={sys.version.split()[0]}")

    try:
        from admin_web.server import create_app
    except Exception as e:
        print(f"❌ import admin_web.server failed: {type(e).__name__}: {e}")
        return 1

    try:
        app = create_app()
        client = app.test_client()
        print("✅ Flask app loaded successfully.")
    except Exception as e:
        print(f"❌ create_app() failed: {type(e).__name__}: {e}")
        return 1

    ok = True
    print("\n=== בדיקת ראוטים עיקריים ===")

    # רשימת ראוטים לבדיקה
    paths = [
        "/version",
        "/healthz",
        "/readyz",
        "/api/logs",
        "/video/stream.mjpg",
        "/video/stream_file.mjpg",
        "/api/video/state",
        "/api/exercises"  # אם קיים
    ]

    for p in paths:
        res = _check(client, p)
        ok = ok and res

    print("\n=== סיכום ===")
    if ok:
        print("🎉 כל הראוטים העיקריים נענו בהצלחה (200 OK).")
        return 0
    else:
        print("⚠️  חלק מהראוטים נכשלו — בדוק לוגים או הרשמות Blueprint.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
