# runpod_proxy.py — Proxy מקומי ל-RunPod עם טיפול נכון ב-headers ודפים דחוסים
from flask import Flask, request, Response
import requests

RUNPOD_BASE = "https://zkt7um55x5h88n.api.runpod.ai"  # נשאר אותו בסיס
API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"  # שלך

app = Flask(__name__)

# Hop-by-hop headers שלא מעבירים לפי RFC
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "upgrade", "transfer-encoding", "content-length"
}

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy(path):
    url = f"{RUNPOD_BASE}/{path}"
    # מעתיקים את ההדרים מהקליינט, בלי Host/Authorization
    fwd_headers = {k: v for k, v in request.headers if k.lower() not in ("host", "authorization")}
    # מוסיפים Authorization של RunPod
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"

    # שולחים את הבקשה ל-RunPod
    resp = requests.request(
        method=request.method,
        url=url,
        headers=fwd_headers,
        params=request.args,
        data=request.get_data(),
        stream=True,          # משאירים stream=True כדי לתמוך ב-MJPEG
        timeout=90,
    )

    # מעבירים חזרה כמעט את כל ההדרים חוץ מ-hop-by-hop
    out_headers = []
    for k, v in resp.headers.items():
        if k.lower() not in HOP_BY_HOP:
            out_headers.append((k, v))

    # אם זה סטרים (למשל MJPEG), נזרום; אחרת נעביר גוף מלא
    ctype = resp.headers.get("Content-Type", "")
    if "multipart" in ctype or "stream" in ctype:
        body = resp.iter_content(chunk_size=8192)
        direct_passthrough = True
    else:
        body = resp.content
        direct_passthrough = False

    return Response(body, status=resp.status_code, headers=out_headers, direct_passthrough=direct_passthrough)

if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
