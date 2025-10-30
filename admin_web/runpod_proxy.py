# -*- coding: utf-8 -*-
"""
RunPod Reverse Proxy + API
--------------------------
ניגשים מקומית דרך http://127.0.0.1:8000, הכל רץ בענן.

תומך:
- דשבורד מלא (reverse proxy ל-CLOUD_PUBLIC_BASE)
- API ישיר ל-RunPod (/api/runpod/run-sync, /run-submit, /status/<id>)
- /healthz ו-/ping
"""

from __future__ import annotations
import os, time, requests
from urllib.parse import urljoin
from flask import Flask, Blueprint, request, Response, jsonify

# ========= קונפיג (דריסת ENV) =========
CLOUD_PUBLIC_BASE = (os.getenv("CLOUD_PUBLIC_BASE") or "https://1fmkdasa1l0x06-8000.proxy.runpod.net").rstrip("/")
RUNPOD_BASE       = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
RUNPOD_API_KEY    = os.getenv("RUNPOD_API_KEY") or "rpa_xxx"  # תחליף במפתח שלך
PORT              = int(os.getenv("PORT", "8000"))
DEBUG             = (os.getenv("PROXY_DEBUG", "1") == "1")

app = Flask(__name__)

# ========= עזרי Proxy =========
HOP_BY_HOP = {
    "connection","keep-alive","proxy-authenticate","proxy-authorization",
    "te","trailers","transfer-encoding","upgrade"
}

def log(*a):
    if DEBUG: print(time.strftime("[%H:%M:%S]"), *a, flush=True)

def _auth_headers():
    return {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Accept-Encoding": "identity"}

def _copy_headers(src):
    return {k: v for k, v in src.items() if k.lower() not in HOP_BY_HOP}

# ========= /api/runpod/* =========
runpod_bp = Blueprint("runpod_api", __name__, url_prefix="/api/runpod")

@runpod_bp.post("/run-sync")
def run_sync():
    try:
        payload = request.get_json(silent=True) or {}
        r = requests.post(
            urljoin(RUNPOD_BASE + "/", "run-sync"),
            json={"input": payload},
            headers=_auth_headers(),
            timeout=(10, 600)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("run-sync EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

@runpod_bp.post("/run-submit")
def run_submit():
    try:
        payload = request.get_json(silent=True) or {}
        r = requests.post(
            urljoin(RUNPOD_BASE + "/", "run"),
            json={"input": payload},
            headers=_auth_headers(),
            timeout=(10, 120)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("run-submit EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

@runpod_bp.get("/status/<job_id>")
def job_status(job_id: str):
    try:
        r = requests.get(
            urljoin(RUNPOD_BASE + "/", f"status/{job_id}"),
            headers=_auth_headers(),
            timeout=(10, 60)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("status EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

app.register_blueprint(runpod_bp)

# ========= Reverse Proxy לכל שאר הנתיבים =========
@app.route('/', defaults={'path': ''}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route('/<path:path>', methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def forward_all(path: str):
    # שמור את /api/runpod ל-Blueprint
    if path.startswith("api/runpod"):
        return jsonify(ok=False, error="reserved_path"), 400

    upstream = urljoin(CLOUD_PUBLIC_BASE.rstrip("/") + "/", path)
    method = request.method
    is_stream = path.endswith(".mjpg") or "stream" in path

    try:
        log("→", method, upstream)
        r = requests.request(
            method, upstream,
            headers=_copy_headers(request.headers),
            data=request.get_data(),
            stream=is_stream,
            timeout=(10, 300),
        )
        hdrs = _copy_headers(r.headers)
        if is_stream:
            def gen():
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            return Response(gen(), status=r.status_code, headers=hdrs)
        return Response(r.content, status=r.status_code, headers=hdrs)
    except Exception as e:
        log("Proxy ERROR:", e)
        return jsonify(ok=False, error="proxy_failed", detail=str(e)), 502

# ========= בריאות =========
@app.get("/healthz")
def healthz():
    return jsonify(ok=True, msg="proxy_ok", port=PORT), 200

@app.get("/ping")
def ping():
    return "pong", 200

# ========= ריצה מקומית =========
if __name__ == "__main__":
    print("\n[RUNPOD PROXY] ✅ Ready")
    print(f"[RUNPOD PROXY] 🌍 Local : http://127.0.0.1:{PORT}")
    print(f"[RUNPOD PROXY] 🔗 UI    : {CLOUD_PUBLIC_BASE}")
    print(f"[RUNPOD PROXY] 🔗 API   : {RUNPOD_BASE}")
    print(f"[RUNPOD PROXY] 🔐 Key   : {RUNPOD_API_KEY[:6]}...{RUNPOD_API_KEY[-5:]}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
