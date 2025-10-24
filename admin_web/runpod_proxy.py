from flask import Flask, request, Response
import requests

RUNPOD_BASE = "https://zkt7um55x5h88n.api.runpod.ai"
API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"

app = Flask(__name__)

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade", "transfer-encoding", "content-length"
}

@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def proxy(path):
    url = f"{RUNPOD_BASE}/{path}"

    # מעתיקים את ההדרים מהלקוח ומנקים מה שלא צריך
    fwd_headers = {k: v for k, v in request.headers if k.lower() not in ("host", "authorization")}

    # 🔒 מפתח ה־API של RunPod
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"

    # ✅ מבקשים מהשרת לא לדחוס (כדי למנוע “ג׳יבריש” בדפדפן)
    fwd_headers["Accept-Encoding"] = "identity"

    resp = requests.request(
        method=request.method,
        url=url,
        headers=fwd_headers,
        params=request.args,
        data=request.get_data(),
        stream=True,   # שומר תמיכה ב־MJPEG וכו'
        timeout=90,
    )

    # מחזירים את רוב ההדרים (ללא hop-by-hop)
    out_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP]

    ctype = resp.headers.get("Content-Type", "")
    if "multipart" in ctype or "stream" in ctype:
        body = resp.iter_content(chunk_size=8192)
        direct_passthrough = True
    else:
        # חשוב: לא לגעת בגוף (להשאיר כפי שהוא)
        body = resp.raw
        direct_passthrough = True

    return Response(body, status=resp.status_code, headers=out_headers, direct_passthrough=direct_passthrough)

if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
