# runpod_proxy.py
from flask import Flask, request, Response
import requests, os

RUNPOD_BASE = os.environ.get("RUNPOD_BASE", "").rstrip("/")
API_KEY     = os.environ.get("RUNPOD_API_KEY", "")

app = Flask(__name__)

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy(path):
    if not RUNPOD_BASE or not API_KEY:
        return Response("Proxy not configured. Set RUNPOD_BASE and RUNPOD_API_KEY.", status=500)

    url = f"{RUNPOD_BASE}/{path}"
    # מעתיקים כותרות מהלקוח, ומחליפים Authorization
    fwd_headers = {k:v for k,v in request.headers if k.lower() not in ("host","content-length","authorization")}
    fwd_headers["Authorization"] = f"Bearer {API_KEY}"

    # שולחים קדימה ל-RunPod
    resp = requests.request(
        method  = request.method,
        url     = url,
        headers = fwd_headers,
        params  = request.args,
        data    = request.get_data(),
        stream  = True,
        timeout = 60,
    )

    # מחזירים תגובה כמו שהיא (למעט כותרות בעייתיות)
    excluded = {"content-encoding","content-length","transfer-encoding","connection"}
    headers  = [(k,v) for k,v in resp.raw.headers.items() if k.lower() not in excluded]
    return Response(resp.iter_content(chunk_size=8192), status=resp.status_code, headers=headers)

if __name__ == "__main__":
    port = int(os.environ.get("LOCAL_PROXY_PORT", "8080"))
    print(f"Local proxy on http://127.0.0.1:{port}  →  {RUNPOD_BASE}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
