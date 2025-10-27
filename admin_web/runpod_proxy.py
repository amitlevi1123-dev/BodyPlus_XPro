# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — תמיכה ב־Serverless API (/run)
# -------------------------------------------------------
# משמש כגשר בין Flask מקומי לבין RunPod Serverless
# אם תבקר ב־http://127.0.0.1:8080 זה ישלח בקשת POST ל־/run
# ויחזיר את התשובה שקיבלת מה-Serverless שלך.
# סטרימינג MJPEG אינו נתמך ב-Serverless.
# -------------------------------------------------------

from flask import Flask, request, Response, jsonify
import os
import json
import requests

# ========= הגדרות =========
RUNPOD_BASE = os.getenv("RUNPOD_BASE", "https://api.runpod.ai/v2/pcw665a3g3k5pk").rstrip("/")
API_KEY = os.getenv("RUNPOD_API_KEY", "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu")

app = Flask(__name__)

# כותרות שלא מעבירים הלאה
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "upgrade", "transfer-encoding", "content-length"
}

# ========= בריאות ודיאגנוסטיקה =========
@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)


@app.get("/_proxy/whoami")
def proxy_whoami():
    return jsonify(
        proxy="runpod-proxy",
        upstream=RUNPOD_BASE,
        api_key_set=bool(API_KEY),
        client_ip=request.remote_addr,
    ), 200


# ========= OPTIONS =========
@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def proxy_options(path):
    resp = Response(status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


# ========= פונקציה מרכזית =========
def call_runpod(input_payload: dict, timeout=(5, 60)):
    """שולחת בקשה ל־RunPod Serverless (מסלול /run)"""
    url = f"{RUNPOD_BASE}/run"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "Accept-Encoding": "identity",
    }
    resp = requests.post(url, headers=headers, json={"input": input_payload}, timeout=timeout)
    return resp


# ========= ראוט ראשי =========
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def proxy(path):
    # מקבלים את גוף הבקשה (אם יש)
    try:
        body = request.get_json(silent=True) or {}
    except Exception:
        body = {}

    # מייצרים payload סטנדרטי שנשלח ל-RunPod
    input_payload = {
        "method": request.method,
        "path": path,
        "args": request.args.to_dict(),
        "body": body,
    }

    try:
        resp = call_runpod(input_payload)
        return Response(resp.content, status=resp.status_code,
                        headers={"Content-Type": resp.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502


# ========= הודעה ברורה למקרה של סטרימינג =========
@app.route("/video/stream.mjpg")
def no_stream_serverless():
    return jsonify(ok=False, error="serverless_no_stream",
                   detail="⚠️ Serverless לא תומך בסטרים MJPEG. השתמש ב־Pod רגיל."), 400


# ========= הרצה מקומית =========
if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod Serverless Endpoint")
    print(f"🔗 Base: {RUNPOD_BASE}")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
