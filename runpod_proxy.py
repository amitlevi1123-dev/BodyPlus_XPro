# runpod_proxy.py — Proxy מקומי לשרת RunPod שלך
from flask import Flask, request, Response
import requests, os

RUNPOD_BASE = "https://zkt7um55x5h88n.api.runpod.ai"
API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"

app = Flask(__name__)

@app.route("/", defaults={"path": ""}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route("/<path:path>", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def proxy(path):
    url = f"{RUNPOD_BASE}/{path}"
    headers = {k:v for k,v in request.headers if k.lower() not in ("host","content-length","authorization")}
    headers["Authorization"] = f"Bearer {API_KEY}"
    try:
        resp = requests.request(
            method=request.method,
            url=url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            stream=True,
            timeout=60,
        )
        excluded = {"content-encoding","content-length","transfer-encoding","connection"}
        headers = [(k,v) for k,v in resp.raw.headers.items() if k.lower() not in excluded]
        return Response(resp.iter_content(chunk_size=8192), status=resp.status_code, headers=headers)
    except Exception as e:
        return Response(f"Proxy error: {e}", status=500)

if __name__ == "__main__":
    print("🔁 Proxy running at http://127.0.0.1:8080 → RunPod")
    app.run(host="127.0.0.1", port=8080, debug=False, threaded=True)
