# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — שימוש בטוח ב-Serverless (ללא הצפות)
# -------------------------------------------------------
# GET  /                → עמוד סטטוס (לא יוצר Job)
# GET  /health          → healthcheck (אליאס)
# GET  /_proxy/health   → healthcheck מפורט
# POST /run-submit      → יוצר Job ב-/run (async)
# POST /run-sync        → מריץ /run-sync (sync)
# GET  /status/<job_id> → סטטוס Job
# ⚠️  סטרים MJPEG לא נתמך ב-Serverless (רק Pod)
# -------------------------------------------------------

from flask import Flask, request, Response, jsonify
import os
import requests

# עדכן כאן אם יצרת Endpoint חדש (או דרך ENV RUNPOD_BASE)
RUNPOD_BASE = os.getenv("RUNPOD_BASE", "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY = os.getenv("RUNPOD_API_KEY", "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu")

app = Flask(__name__)

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "upgrade", "transfer-encoding", "content-length"
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

# ---------- דף בית (לא יוצר Job) ----------
@app.get("/")
def home_page():
    return jsonify(
        ok=True,
        msg="RunPod proxy alive. Use POST /run-submit (async) or POST /run-sync (sync).",
        upstream=RUNPOD_BASE
    ), 200

# ---------- Health ----------
@app.get("/health")
def health_alias():
    return jsonify(ok=True, upstream=RUNPOD_BASE), 200

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
    # דפדפנים מבקשים את זה אוטומטית – נמנע לוגים/טראפיק
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
    print("🔁 Proxy running at http://0.0.0.0:5000 → RunPod Serverless Endpoint")
    print(f"🔗 Base: {RUNPOD_BASE}")
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
