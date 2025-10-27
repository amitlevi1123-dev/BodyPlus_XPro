# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — כניסה לאתר ב-/  + תמיכה ב-MJPEG
# -------------------------------------------------------

from flask import Flask, request, Response, jsonify
import os
import requests

RUNPOD_BASE = os.getenv("RUNPOD_BASE", "https://zkt7um55x5h88n.api.runpod.ai").rstrip("/")
API_KEY = os.getenv("RUNPOD_API_KEY", "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu")

# נתיב ברירת מחדל כשמבקרים את השורש "/" (ניתן לשנות ל'dashboard' אם תרצה)
DEFAULT_SITE_PATHS = ("ui", "dashboard", "")  # ינסה לפי הסדר: /ui → /dashboard → /

app = Flask(__name__)

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "upgrade", "transfer-encoding", "content-length"
}

# ---------- בריאות ודיאגנוסטיקה ----------
@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)

@app.get("/_proxy/whoami")
def proxy_whoami():
    return jsonify(proxy="runpod-proxy", upstream=RUNPOD_BASE, api_key_set=bool(API_KEY),
                   client_ip=request.remote_addr), 200

# ---------- OPTIONS ----------
@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def proxy_options(path):
    resp = Response(status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

def _forward(method, path, args, body, timeout=(5, 30)):
    url = f"{RUNPOD_BASE}/{path.lstrip('/')}"
    fwd_headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "authorization") or lk in HOP_BY_HOP:
            continue
        fwd_headers[k] = v
    fwd_headers["X-Forwarded-For"] = request.remote_addr or ""
    fwd_headers["X-Forwarded-Proto"] = "https"
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"
    fwd_headers["Accept-Encoding"] = "identity"

    resp = requests.request(method=method, url=url, headers=fwd_headers,
                            params=args, data=body, stream=True, timeout=timeout)
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP]

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if any(x in ctype for x in ("multipart", "mjpeg", "stream")):
        return Response(resp.iter_content(chunk_size=8192),
                        status=resp.status_code, headers=out_headers, direct_passthrough=True)
    return Response(resp.content, status=resp.status_code, headers=out_headers)

# ---------- Proxy ראשי ----------
@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
def proxy(path):
    # שורש "/" → נטען את האתר (ui/dashboard/…)
    if path in ("", "/"):
        body = request.get_data(cache=False, as_text=False)
        # ננסה /ui ואז /dashboard ואז /
        for candidate in DEFAULT_SITE_PATHS:
            try:
                return _forward(request.method, candidate, request.args, body, timeout=(5, 30))
            except requests.RequestException:
                continue
        # fallback אחרון: healthz כדי לתת אינדיקציה שהשרת חי
        try:
            return _forward("GET", "healthz", {}, b"", timeout=(3, 10))
        except requests.RequestException as e:
            return jsonify(ok=False, error="upstream_unreachable", detail=str(e)), 502

    # כל יתר הנתיבים—מעבירים אחד לאחד
    try:
        return _forward(request.method, path, request.args, request.get_data(cache=False, as_text=False))
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- הרצה מקומית ----------
if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    print(f"🔗 Base: {RUNPOD_BASE}")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
