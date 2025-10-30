# -*- coding: utf-8 -*-
"""
RunPod Reverse-Proxy + API
==========================
מגיש *את כל הדשבורד מהענן* בכתובת המקומית http://127.0.0.1:8000
וגם חושף /api/runpod/* ל-RunPod API (run-sync/run-submit/status).

ENV החשובים (אפשר להשאיר ברירת-מחדל ולעדכן אחר-כך):
- RUNPOD_UI_BASE   = https://<endpoint-id>-8000.proxy.runpod.net
- RUNPOD_API_BASE  = https://api.runpod.ai/v2/<endpoint-id>
- RUNPOD_API_KEY   = rpa_********
- PORT             = 8000
"""
from __future__ import annotations
import os, sys, json, time, traceback
from urllib.parse import urljoin, urlparse, urlencode
from flask import Flask, Blueprint, request, Response, jsonify
import requests

# -------- קונפיג (כולל ערכי ברירת-מחדל שמיד עובדים) --------
UI_BASE  = (os.getenv("RUNPOD_UI_BASE")  or "https://1fmkdasa1l0x06-8000.proxy.runpod.net").rstrip("/")
API_BASE = (os.getenv("RUNPOD_API_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY  =  os.getenv("RUNPOD_API_KEY") or "rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21"
PORT     = int(os.getenv("PORT", "8000"))
DEBUG    = (os.getenv("PROXY_DEBUG", "0") == "1")

# -------- טוען את כל ה-UI המקומי (routes/blueprints) כדי לא לשבור URL פנימיים --------
# שורש "/" נשאר אצלנו — אבל אנחנו מעבירים הכל הלאה לענן.
from admin_web.server import create_app
app: Flask = create_app()

# -------- עזרי רישום/כותרות --------
HOP_BY_HOP = {"connection","keep-alive","proxy-authenticate","proxy-authorization","te","trailers","transfer-encoding","upgrade"}

def log(*a):
    if DEBUG: print(time.strftime("[%H:%M:%S]"), *a, flush=True)

def _auth_headers():
    return {"Authorization": f"Bearer {API_KEY}", "Accept-Encoding": "identity"}

def _copy_headers(src):
    return {k: v for k, v in src.items() if k.lower() not in HOP_BY_HOP}

def _request_upstream(method: str, url: str, stream: bool = False):
    # מעביר query/body/headers כמו שהם
    params = request.query_string.decode("utf-8", errors="ignore")
    up_url = url if not params else (f"{url}?{params}")
    headers = _copy_headers(request.headers)
    # אל תשלח Host מקומי לענן
    headers.pop("Host", None)
    # במידת הצורך הוסף Authorization לדשבורד (בד"כ לא צריך)
    # headers.update(_auth_headers())
    data = request.get_data() if method in ("POST","PUT","PATCH","DELETE") else None
    return requests.request(method, up_url, headers=headers, data=data, stream=stream, timeout=(10, 300), allow_redirects=False)

# -------- Proxy ל-RunPod API (נפרד) --------
proxy_bp = Blueprint("runpod_proxy", __name__, url_prefix="/api/runpod")

@proxy_bp.post("/run-sync")
def run_sync():
    try:
        r = requests.post(urljoin(API_BASE + "/", "run-sync"), json={"input": (request.get_json(silent=True) or {})},
                          headers={"Content-Type":"application/json", **_auth_headers()}, timeout=(10, 600))
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("EXC run-sync:", repr(e)); log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

@proxy_bp.post("/run-submit")
def run_submit():
    try:
        r = requests.post(urljoin(API_BASE + "/", "run"), json={"input": (request.get_json(silent=True) or {})},
                          headers={"Content-Type":"application/json", **_auth_headers()}, timeout=(10, 60))
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("EXC run-submit:", repr(e)); log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

@proxy_bp.get("/status/<job_id>")
def job_status(job_id: str):
    try:
        r = requests.get(urljoin(API_BASE + "/", f"status/{job_id}"),
                         headers=_auth_headers(), timeout=(10, 60))
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("EXC status:", repr(e)); log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

app.register_blueprint(proxy_bp)

# -------- בריאות מקומי --------
@app.get("/healthz")
def _healthz(): return "ok", 200
@app.get("/ping")
def _ping():    return "pong", 200

# -------- Reverse-Proxy לכל שאר הנתיבים (UI, API פנימי, סטרים, וכו') --------
# שים לב: זה תופס גם "/" — כלומר כניסה ל-127.0.0.1:8000 תציג את הדשבורד מהענן.
@app.route('/', defaults={'path': ''}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route('/<path:path>', methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def forward_all(path: str):
    # אל תתפוס את /api/runpod/*
    if path.startswith("api/runpod"):
        return jsonify(ok=False, error="use_/api/runpod_prefix"), 400

    # כתובת למעלה בענן
    upstream = urljoin(UI_BASE.rstrip("/") + "/", path)
    method = request.method.upper()
    # סטרימים כמו /video/stream.mjpg צריכים stream=True
    is_stream = path.endswith(".mjpg") or "stream" in path

    try:
        r = _request_upstream(method, upstream, stream=is_stream)
        hdrs = _copy_headers(r.headers)

        if is_stream:
            def gen():
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk: yield chunk
            return Response(gen(), status=r.status_code, headers=hdrs)
        else:
            return Response(r.content, status=r.status_code, headers=hdrs)

    except requests.RequestException as e:
        log("UPSTREAM ERR", method, upstream, "->", repr(e))
        return jsonify(ok=False, error="upstream_failed", detail=str(e), upstream=UI_BASE), 502

# -------- CORS עדין (רק אם צריך) --------
@app.after_request
def _cors(resp):
    resp.headers.setdefault("Access-Control-Allow-Origin", "*")
    resp.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, PATCH, DELETE")
    resp.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization")
    return resp

# -------- הדפסות נוחות --------
def _mask(k: str) -> str:
    return "" if not k else ("***" if len(k) <= 10 else f"{k[:6]}...{k[-5:]}")

if __name__ == "__main__":
    print("[RUNPOD] ✅ Reverse-proxy ready (UI+API)")
    print(f"[RUNPOD] 🌍 Local  : http://127.0.0.1:{PORT}")
    print(f"[RUNPOD] 🔗 UI_BASE: {UI_BASE}")
    print(f"[RUNPOD] 🔗 API_BASE: {API_BASE}")
    print(f"[RUNPOD] 🔐 API Key: {_mask(API_KEY)}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
