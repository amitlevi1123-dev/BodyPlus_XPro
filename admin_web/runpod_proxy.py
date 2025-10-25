# -*- coding: utf-8 -*-
# -------------------------------------------------------
# 🔁 RunPod Proxy — גרסה פשוטה ונקייה (לאבטיפוס)
# שומר על תמיכה בזרמי MJPEG, תיקון כותרות והדפסות בריאות
# -------------------------------------------------------

from flask import Flask, request, Response, jsonify
import requests

# ========= קונפיג (נשאר ישירות בקוד לאבטיפוס) =========
RUNPOD_BASE = "https://zkt7um55x5h88n.api.runpod.ai"
API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"

app = Flask(__name__)

# כותרות שלא מעבירים הלאה
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "upgrade", "transfer-encoding", "content-length"
}


# ========= מסלולים פנימיים לבריאות ודיאגנוסטיקה =========
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
    return Response(status=204)


# ========= Proxy ראשי =========
@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
def proxy(path):
    # בונים את היעד
    url = f"{RUNPOD_BASE.rstrip('/')}/{path.lstrip('/')}"

    # מעתיקים את ההדרים מהלקוח ומנקים מה שלא צריך
    fwd_headers = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in ("host", "authorization"):
            continue
        if lk in HOP_BY_HOP:
            continue
        fwd_headers[k] = v

    # 🔒 מפתח ה־API של RunPod
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"

    # ✅ מבקשים מהשרת לא לדחוס (כדי למנוע “ג׳יבריש” בדפדפן)
    fwd_headers["Accept-Encoding"] = "identity"

    # גוף הבקשה
    data = request.get_data(cache=False, as_text=False)

    try:
        resp = requests.request(
            method=request.method,
            url=url,
            headers=fwd_headers,
            params=request.args,
            data=data,
            stream=True,  # שומר תמיכה ב־MJPEG וכו'
            timeout=(5, 90),  # (connect, read)
        )
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

    # מנקים כותרות hop-by-hop
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP]

    # מזהים אם מדובר בזרם (MJPEG, multipart וכו’)
    ctype = resp.headers.get("Content-Type", "")
    is_stream = any(x in ctype for x in ("multipart", "stream", "mjpeg"))

    if is_stream:
        # מצב סטרים (וידאו)
        body = resp.iter_content(chunk_size=8192)
        return Response(body, status=resp.status_code, headers=out_headers, direct_passthrough=True)

    # מצב רגיל — מעבירים תוכן כמו שהוא
    return Response(resp.raw, status=resp.status_code, headers=out_headers, direct_passthrough=True)


# ========= הרצה מקומית =========
if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    print(f"🔗 Base: {RUNPOD_BASE}")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
