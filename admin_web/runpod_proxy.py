# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — גרסה יציבה לאבטיפוס
# -------------------------------------------------------

from flask import Flask, request, Response, jsonify
import requests

# ========= קונפיג (נשאר בקובץ לאבטיפוס) =========
RUNPOD_BASE = "https://zkt7um55x5h88n.api.runpod.ai"
API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"

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
        client_ip=request.remote_addr
    ), 200

# ========= Preflight (CORS OPTIONS) =========
@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def proxy_options(path):
    resp = Response(status=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

# ========= Proxy ראשי =========
@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
def proxy(path):
    # שורש → healthz כדי למנוע timeout מיותר
    if path in ("", "/"):
        path = "healthz"

    url = f"{RUNPOD_BASE.rstrip('/')}/{path.lstrip('/')}"

    # בונים כותרות להעברה, ללא hop-by-hop/host/auth מהלקוח
    fwd_headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "authorization") or lk in HOP_BY_HOP:
            continue
        fwd_headers[k] = v

    # מזהי פרוקסי
    fwd_headers["X-Forwarded-For"] = request.remote_addr or ""
    fwd_headers["X-Forwarded-Proto"] = "https"

    # 🔒 מפתח ה־API של RunPod
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"

    # מניעת דחיסה (מפחית בעיות תצוגה)
    fwd_headers["Accept-Encoding"] = "identity"

    # גוף הבקשה (בדיוק כפי שהתקבל)
    data = request.get_data(cache=False, as_text=False)

    try:
        upstream = requests.request(
            method=request.method,
            url=url,
            headers=fwd_headers,
            params=request.args,
            data=data,
            stream=True,           # כדי לאפשר MJPEG/streams
            timeout=(5, 30),       # (connect, read)
        )
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

    # מנקים כותרות hop-by-hop מהתשובה
    out_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP]

    # זיהוי סטרים (MJPEG/Multipart)
    ctype = upstream.headers.get("Content-Type", "") or ""
    is_stream = any(x in ctype.lower() for x in ("multipart", "mjpeg", "stream"))

    if is_stream:
        body = upstream.iter_content(chunk_size=8192)
        return Response(body, status=upstream.status_code, headers=out_headers, direct_passthrough=True)

    # מצב רגיל — החזר תוכן כ־bytes (לא raw)
    return Response(upstream.content, status=upstream.status_code, headers=out_headers)

# ========= הרצה מקומית =========
if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    print(f"🔗 Base: {RUNPOD_BASE}")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
