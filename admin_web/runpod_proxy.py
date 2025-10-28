# admin_web/runpod_proxy.py — Proxy יחיד ל-RunPod Serverless
from flask import Flask, request, Response, jsonify
import os, requests

# ⛳ יעד יחיד (Serverless Endpoint)
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY = os.getenv("RUNPOD_API_KEY") or "rpa_JMCLGONT7MUZLIX6CXDZWLOSR8VAS3RMD1MVRL0A19qjux"

app = Flask(__name__)

# --------- עזרי HTTP ---------
def _headers_auth():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept-Encoding": "identity",
    }

def _post(url: str, payload: dict, timeout=(5, 300)):
    h = {"Content-Type": "application/json", **_headers_auth()}
    return requests.post(url, json=payload, headers=h, timeout=timeout)

def _get(url: str, timeout=(5, 60)):
    return requests.get(url, headers=_headers_auth(), timeout=timeout)

# --------- CORS / favicon ---------
@app.route("/", methods=["OPTIONS"])
@app.route("/run-submit", methods=["OPTIONS"])
@app.route("/run-sync", methods=["OPTIONS"])
@app.route("/status/<job_id>", methods=["OPTIONS"])
def _opts(job_id=None):
    r = Response(status=204)
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return r

@app.get("/favicon.ico")
def _fav():
    return Response(status=204)

# --------- דף בית / בריאות ---------
@app.get("/")
def home():
    return jsonify(
        ok=True,
        msg="RunPod proxy alive. Use POST /run-submit (async) or /run-sync (sync).",
        upstream=RUNPOD_BASE,
    ), 200

@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)

@app.get("/health")
def health_alias():
    return jsonify(ok=True), 200

# --------- הרצות ---------
def _require_key():
    if not API_KEY:
        return jsonify(ok=False, error="missing_api_key", hint="set RUNPOD_API_KEY env"), 401

@app.post("/run-sync")
def run_sync():
    if not API_KEY:
        return _require_key()
    body = request.get_json(silent=True) or {}
    try:
        resp = _post(f"{RUNPOD_BASE}/run-sync", {"input": body})
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

@app.post("/run-submit")
def run_submit():
    if not API_KEY:
        return _require_key()
    body = request.get_json(silent=True) or {}
    try:
        resp = _post(f"{RUNPOD_BASE}/run", {"input": body})
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

@app.get("/status/<job_id>")
def status(job_id: str):
    if not API_KEY:
        return _require_key()
    try:
        resp = _get(f"{RUNPOD_BASE}/status/{job_id}")
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# --------- חסימת סטרים (לא נתמך ב-Serverless) ---------
@app.get("/video/stream.mjpg")
def no_stream():
    return jsonify(ok=False, error="serverless_no_stream",
                   detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod."), 400

# --------- הרצה ---------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"🔁 Proxy running at http://127.0.0.1:{port} → {RUNPOD_BASE}")
    print(f"🔐 API key loaded? {'YES' if API_KEY else 'NO'}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
