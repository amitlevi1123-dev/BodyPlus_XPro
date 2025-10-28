# admin_web/runpod_proxy.py  —  Proxy אחד ברור ל־RunPod Serverless
from flask import Flask, request, Response, jsonify
import os, requests

# כתובת יחידה של ה־Endpoint שלך (Serverless)
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
# מפתח API (מומלץ לשים ב־ENV; אם לא קיים — יהיה ריק וזה יופיע ב-/ _proxy/health)
API_KEY = os.getenv("rpa_JMCLGONT7MUZLIX6CXDZWLOSR8VAS3RMD1MVRL0A19qjux") or ""

app = Flask(__name__)

# ---------- עזרי HTTP ----------
def _post(url: str, json_body: dict, timeout=(5, 180)):
    return requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            "Accept-Encoding": "identity",
        },
        json=json_body,
        timeout=timeout,
    )

def _get(url: str, timeout=(5, 60)):
    return requests.get(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Accept-Encoding": "identity",
        },
        timeout=timeout,
    )

# ---------- דף בית / בריאות ----------
@app.get("/")
def home():
    return jsonify(ok=True, msg="RunPod proxy alive. Use POST /run-submit or /run-sync.", upstream=RUNPOD_BASE), 200

@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)

# ---------- הרצה מסונכרנת ----------
@app.post("/run-sync")
def run_sync():
    body = request.get_json(silent=True) or {}
    try:
        r = _post(f"{RUNPOD_BASE}/run-sync", {"input": body}, timeout=(5, 300))
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- הרצה אסינכרונית + סטטוס ----------
@app.post("/run-submit")
def run_submit():
    body = request.get_json(silent=True) or {}
    try:
        r = _post(f"{RUNPOD_BASE}/run", {"input": body})
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

@app.get("/status/<job_id>")
def job_status(job_id: str):
    try:
        r = _get(f"{RUNPOD_BASE}/status/{job_id}")
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except requests.RequestException as e:
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ---------- חסימה לסטרים (לא נתמך ב־Serverless) ----------
@app.get("/video/stream.mjpg")
def no_stream():
    return jsonify(ok=False, error="serverless_no_stream", detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod."), 400

# ---------- הרצה ----------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"🔁 Proxy running at http://127.0.0.1:{port}  →  {RUNPOD_BASE}")
    print(f"🔐 API key loaded? {'YES' if API_KEY else 'NO'}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
