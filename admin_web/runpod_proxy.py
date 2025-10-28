# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — טוען .env בלי תלות חיצונית
# -------------------------------------------------------
from flask import Flask, request, Response, jsonify
import os, requests

# --- טוען .env מקומי בלי python-dotenv ---
def _load_env_file(path: str):
    try:
        if not os.path.isfile(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('\'"')
                # לא נדרוס ENV קיים
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

# טען קודם .env בשורש הפרויקט ואז .venv/.env אם קיים
_load_env_file(os.path.join(os.getcwd(), ".env"))
_load_env_file(os.path.join(os.getcwd(), ".venv", ".env"))

# --- ENV עם ברירות מחדל בטוחות ---
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/pcw665a3g3k5pk").rstrip("/")
API_KEY     = os.getenv("RUNPOD_API_KEY") or ""
PORT        = int(os.getenv("PORT") or "5000")

app = Flask(__name__)

HOP_BY_HOP = {
    "connection","keep-alive","proxy-authenticate","proxy-authorization",
    "te","trailer","trailers","upgrade","transfer-encoding","content-length"
}

# ---------- CORS / OPTIONS ----------
@app.route("/", methods=["OPTIONS"])
@app.route("/run-submit", methods=["OPTIONS"])
@app.route("/run-sync", methods=["OPTIONS"])
@app.route("/status/<job_id>", methods=["OPTIONS"])
def proxy_options(job_id=None):
    resp = Response(status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

# ---------- עוזרי HTTP ----------
def _post(url: str, json_body: dict, timeout=(5, 120)):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "Accept-Encoding": "identity",
    }
    return requests.post(url, headers=headers, json=json_body, timeout=timeout)

def _get(url: str, timeout=(5, 60)):
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept-Encoding": "identity",
    }
    return requests.get(url, headers=headers, timeout=timeout)

# ---------- Home / Health ----------
@app.get("/")
def home_page():
    return jsonify(ok=True, msg="RunPod proxy alive. Use POST /run-submit (async) or POST /run-sync (sync).",
                   upstream=RUNPOD_BASE), 200

@app.get("/health")
def health_alias():
    return jsonify(ok=True, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), 200

@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)

@app.get("/_proxy/whoami")
def proxy_whoami():
    return jsonify(proxy="runpod-proxy", upstream=RUNPOD_BASE, api_key_set=bool(API_KEY),
                   client_ip=request.remote_addr), 200

@app.get("/favicon.ico")
def favicon_noop():
    return Response(status=204)

# ---------- יצירת Job (async) ----------
@app.post("/run-submit")
def run_submit():
    body = request.get_json(silent=True) or {}
    try:
        resp = _post(f"{RUNPOD_BASE}/run", {"input": body})
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- הרצה מסונכרנת (sync) ----------
@app.post("/run-sync")
def run_sync():
    body = request.get_json(silent=True) or {}
    try:
        resp = _post(f"{RUNPOD_BASE}/run-sync", {"input": body}, timeout=(5, 300))
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- סטטוס Job ----------
@app.get("/status/<job_id>")
def job_status(job_id: str):
    try:
        resp = _get(f"{RUNPOD_BASE}/status/{job_id}")
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- חסימת סטרים MJPEG ----------
@app.get("/video/stream.mjpg")
def no_stream_serverless():
    return jsonify(ok=False, error="serverless_no_stream",
                   detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod או WebSocket."), 400

# ---------- הרצה מקומית ----------
if __name__ == "__main__":
    print(f"🔁 Proxy running at http://0.0.0.0:{PORT} → {RUNPOD_BASE}")
    print(f"🔐 API key loaded? {'YES' if API_KEY else 'NO'}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
