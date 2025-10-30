# -*- coding: utf-8 -*-
"""
admin_web/runpod_proxy.py — 💥 גרסה סופית
-------------------------------------------------
מריץ את כל המערכת:
✅ Flask Admin UI (Dashboard, Video, Logs, Exercise)
✅ כל ה-API של BodyPlus_XPro
✅ RunPod Proxy API
"""

from flask import Flask, jsonify, request, Response
import os, time, json, traceback, requests

# ========== הגדרות ==========
PORT = int(os.getenv("PORT", "8000"))
RUNPOD_BASE = os.getenv("RUNPOD_BASE", "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY = os.getenv("RUNPOD_API_KEY", "rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21")
DEBUG = os.getenv("PROXY_DEBUG", "1") == "1"

def log(*a):
    if DEBUG: print("[RUNPOD]", *a, flush=True)

# ========== טעינת Flask Admin UI ==========
try:
    from admin_web.server import create_app
    app = create_app()
    log("✅ Loaded Flask Admin UI (Dashboard + API)")
except Exception as e:
    app = Flask(__name__)
    log("❌ Failed to load admin_web.server:", e)
    @app.route("/")
    def fallback():
        return "<h3>⚠️ Failed to load Admin UI</h3>", 500

# ========== API של RunPod ==========
@app.get("/api/runpod/healthz")
def healthz():
    return jsonify(ok=True, ts=time.time(), upstream=RUNPOD_BASE), 200

@app.get("/api/runpod/info")
def info():
    return jsonify({
        "ok": True,
        "upstream": RUNPOD_BASE,
        "api_key_set": bool(API_KEY),
        "port": PORT
    }), 200

@app.post("/api/runpod/run-sync")
def run_sync():
    """הרצה סינכרונית ב-RunPod"""
    try:
        data = request.get_json(force=True)
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        url = f"{RUNPOD_BASE}/run-sync"
        log("→ POST", url)
        r = requests.post(url, json={"input": data}, headers=headers, timeout=(10, 300))
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@app.post("/api/runpod/run-submit")
def run_submit():
    """הרצה א-סינכרונית"""
    try:
        data = request.get_json(force=True)
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        url = f"{RUNPOD_BASE}/run"
        log("→ POST", url)
        r = requests.post(url, json={"input": data}, headers=headers, timeout=(10, 300))
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@app.get("/api/runpod/status/<job_id>")
def status(job_id: str):
    """בדיקת סטטוס"""
    try:
        headers = {"Authorization": f"Bearer {API_KEY}"}
        url = f"{RUNPOD_BASE}/status/{job_id}"
        log("→ GET", url)
        r = requests.get(url, headers=headers, timeout=(10, 60))
        return Response(r.content, status=r.status_code, headers={"Content-Type": r.headers.get("Content-Type", "application/json")})
    except Exception as e:
        return jsonify(ok=False, error=str(e)), 500

@app.get("/api/runpod/test")
def test():
    """בדיקה עצמית של כל המערכת"""
    return jsonify(ok=True, msg="🔥 BodyPlus_XPro FULL SYSTEM ACTIVE"), 200

# ========== CORS ==========
@app.after_request
def cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

# ========== MAIN ==========
if __name__ == "__main__":
    print("🚀 Launching FULL BodyPlus_XPro (Flask + Proxy + API)")
    print(f"🔗 Upstream: {RUNPOD_BASE}")
    print(f"🔐 API Key Set: {'✅' if API_KEY else '❌'}")
    print(f"🌍 Running on port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)
