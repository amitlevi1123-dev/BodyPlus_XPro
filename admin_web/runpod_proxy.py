# -*- coding: utf-8 -*-
"""
admin_web/runpod_proxy.py — גרסה משולבת (Proxy + Dashboard + Main)
-------------------------------------------------------------------
קובץ זה מפעיל את כל המערכת: גם Flask Proxy, גם ה-Admin Dashboard וגם את ה-main app.
אם Flask או main נכשלים, הוא חוזר אוטומטית רק לפרוקסי כדי שלא תישאר בלי שרת.
"""

from __future__ import annotations
from flask import Flask, request, Response, jsonify, make_response
import os, json, time, traceback, requests, threading, subprocess, sys

# ========= קונפיג (ניתן לדרוס ע"י משתני סביבה) =========
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY     = os.getenv("RUNPOD_API_KEY") or "rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21"
PORT        = int(os.getenv("PORT", "8000"))
DEBUG_LOG   = (os.getenv("PROXY_DEBUG", "1") == "1")  # 1=on, 0=off

_LAST = {"when": None, "path": None, "method": None, "status": None, "upstream": None, "resp_head": {}, "resp_text": None}
app = Flask(__name__)

# ========= עזרי לוג =========
def log(*args):
    if DEBUG_LOG:
        ts = time.strftime("[%H:%M:%S]")
        print(ts, *args, flush=True)

def _mask_key(k: str) -> str:
    return "***" if not k or len(k) <= 8 else f"{k[:6]}...{k[-5:]}"

def _short_headers(h: dict, drop=None):
    if drop is None: drop = {"cookie", "authorization"}
    out = {}
    for k, v in h.items():
        out[k] = "<hidden>" if k.lower() in drop else (v if len(str(v)) < 200 else str(v)[:200] + " ...")
    return out

def _json_or_text(r: requests.Response) -> str:
    text = r.text
    return text if len(text) < 2000 else text[:2000] + "\n... [truncated] ..."

# ========= עזרי HTTP =========
def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Accept-Encoding": "identity"}

def _post(url: str, payload: dict, timeout=(5, 300)) -> requests.Response:
    return requests.post(url, json=payload, headers={"Content-Type": "application/json", **_auth_headers()}, timeout=timeout)

def _get(url: str, timeout=(5, 60)) -> requests.Response:
    return requests.get(url, headers=_auth_headers(), timeout=timeout)

# ========= CORS =========
@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

# ========= Routes =========
@app.route("/", methods=["GET"])
def home():
    payload = {
        "ok": True,
        "msg": "BodyPlus_XPro full system active (Proxy + Main + Admin)",
        "port": PORT,
        "upstream": RUNPOD_BASE,
        "api_key_mask": _mask_key(API_KEY),
    }
    return jsonify(payload), 200

@app.get("/healthz")
def healthz():
    return jsonify(ok=True, ts=time.time(), upstream=RUNPOD_BASE), 200

@app.get("/_proxy/last")
def last():
    return jsonify(_LAST), 200

@app.post("/run-sync")
def run_sync():
    try:
        body = request.get_json(silent=True) or {}
        up = f"{RUNPOD_BASE}/run-sync"
        r = _post(up, {"input": body})
        text = _json_or_text(r)
        _LAST.update({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": "/run-sync",
            "method": "POST",
            "status": r.status_code,
            "upstream": up,
            "resp_text": text,
        })
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

@app.get("/video/stream.mjpg")
def no_stream():
    return jsonify(ok=False, error="serverless_no_stream", detail="Serverless לא תומך ב-MJPEG. השתמש בשרת קבוע."), 400

# ========= הפעלת main של BodyPlus =========
def start_main_app():
    """פותח את app/main.py בתהליך נפרד כדי לא לחסום את Flask"""
    try:
        log("🧠 Launching BodyPlus_XPro main app...")
        cmd = [sys.executable, "app/main.py"]
        env = os.environ.copy()
        env["NO_CAMERA"] = "1"
        subprocess.Popen(cmd, env=env)
        log("✅ main.py started in background.")
    except Exception as e:
        log("❌ Failed to start main.py:", e)

# ========= main =========
if __name__ == "__main__":
    print(f"🚀 Launching BodyPlus_XPro full system on http://0.0.0.0:{PORT}")
    print(f"🔐 API key loaded? {_mask_key(API_KEY) if API_KEY else 'NO'}")
    print(f"🪵 DEBUG_LOG={'True' if DEBUG_LOG else 'False'}")

    # מפעיל את main app (כולל הוידאו, הזיהוי, החישובים וכו’)
    threading.Thread(target=start_main_app, daemon=True).start()

    try:
        # מנסה להפעיל את ה־Dashboard (Flask Admin)
        from admin_web.server import create_app
        app_flask = create_app()
        app_flask.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)
    except Exception as e:
        print("⚠️ Dashboard failed, fallback to proxy-only mode.")
        print("שגיאה:", e)
        app.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)
