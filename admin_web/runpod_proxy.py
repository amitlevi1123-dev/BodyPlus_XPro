# -*- coding: utf-8 -*-
"""
RunPod Reverse Proxy + API
--------------------------
ניגשים מקומית דרך http://127.0.0.1:8000, הכל רץ בענן.

תומך:
- דשבורד מלא (reverse proxy ל-CLOUD_PUBLIC_BASE)
- API ישיר ל-RunPod (/api/runpod/run-sync, /run-submit, /status/<id>)
- /healthz ו-/ping
"""

from __future__ import annotations
import os, time, requests
from urllib.parse import urljoin
from flask import Flask, Blueprint, request, Response, jsonify

# ========= קונפיג (דריסת ENV) =========
CLOUD_PUBLIC_BASE = (os.getenv("CLOUD_PUBLIC_BASE") or "https://1fmkdasa1l0x06-8000.proxy.runpod.net").rstrip("/")
RUNPOD_BASE       = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
RUNPOD_API_KEY    = os.getenv("RUNPOD_API_KEY") or "rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21"  # החלף במפתח שלך בסביבת הרצה
PORT              = int(os.getenv("PORT", "8000"))
DEBUG             = (os.getenv("PROXY_DEBUG", "1") == "1")

app = Flask(__name__)

# ========= עזרי Proxy =========
# Hop-by-hop headers שאסור להעביר
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade"
}

# כותרות ש-Cloudflare/פרוקסי ציבורי לא אוהבים כשמעבירים הלאה
STRIP_ALWAYS = {
    "host", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto",
    "cf-connecting-ip", "cf-ipcountry", "cf-ray", "cf-visitor"
}

def log(*a):
    if DEBUG:
        print(time.strftime("[%H:%M:%S]"), *a, flush=True)

def _auth_headers():
    # שומר על encoding זהה כדי לא לשבור סטרימים
    return {"Authorization": f"Bearer {RUNPOD_API_KEY}", "Accept-Encoding": "identity"}

def _copy_headers(src):
    # מסיר hop-by-hop + כותרות שעלולות לגרום ל-403 בענן
    out = {}
    for k, v in src.items():
        kl = k.lower()
        if kl in HOP_BY_HOP or kl in STRIP_ALWAYS:
            continue
        out[k] = v
    # הבטחת עקביות בסטרים (ללא דחיסות משונות בצד המקור)
    out.setdefault("Accept-Encoding", "identity")
    return out

# ========= /api/runpod/* =========
runpod_bp = Blueprint("runpod_api", __name__, url_prefix="/api/runpod")

@runpod_bp.post("/run-sync")
def run_sync():
    """
    קריאה סינכרונית ל-RunPod (חוסמת עד החזרה)
    גוף הבקשה שלנו: JSON כללי → נעטוף תחת {"input": ...} לפי API של RunPod
    """
    try:
        payload = request.get_json(silent=True) or {}
        r = requests.post(
            urljoin(RUNPOD_BASE + "/", "run-sync"),
            json={"input": payload},
            headers=_auth_headers(),
            timeout=(10, 600)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("run-sync EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

@runpod_bp.post("/run-submit")
def run_submit():
    """
    קריאה אסינכרונית ל-RunPod (יוצרת job ומחזירה מזהה)
    """
    try:
        payload = request.get_json(silent=True) or {}
        r = requests.post(
            urljoin(RUNPOD_BASE + "/", "run"),
            json={"input": payload},
            headers=_auth_headers(),
            timeout=(10, 120)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("run-submit EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

@runpod_bp.get("/status/<job_id>")
def job_status(job_id: str):
    """
    סטטוס של job אסינכרוני
    """
    try:
        r = requests.get(
            urljoin(RUNPOD_BASE + "/", f"status/{job_id}"),
            headers=_auth_headers(),
            timeout=(10, 60)
        )
        return Response(r.content, status=r.status_code, headers=_copy_headers(r.headers))
    except Exception as e:
        log("status EXC:", e)
        return jsonify(ok=False, error=str(e)), 500

app.register_blueprint(runpod_bp)

# ========= Reverse Proxy לכל שאר הנתיבים =========
@app.route('/', defaults={'path': ''}, methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
@app.route('/<path:path>', methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"])
def forward_all(path: str):
    """
    כל בקשה שאינה /api/runpod/* – מנותבת ל-CLOUD_PUBLIC_BASE, כולל querystring.
    תומך גם ב-MJPEG ובכל זרימה ארוכה.
    """
    # השאר את /api/runpod ל-Blueprint
    if path.startswith("api/runpod"):
        return jsonify(ok=False, error="reserved_path"), 400

    upstream = urljoin(CLOUD_PUBLIC_BASE.rstrip("/") + "/", path)
    method = request.method
    is_stream = path.endswith(".mjpg") or "stream" in path

    try:
        log("→", method, upstream, dict(request.args))
        r = requests.request(
            method,
            upstream,
            headers=_copy_headers(request.headers),
            params=request.args,                 # ✅ לשימור כל ה-querystring
            data=request.get_data(),
            stream=is_stream,
            timeout=(10, 300),
        )
        hdrs = _copy_headers(r.headers)
        if is_stream:
            def gen():
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            return Response(gen(), status=r.status_code, headers=hdrs)
        return Response(r.content, status=r.status_code, headers=hdrs)
    except Exception as e:
        log("Proxy ERROR:", e)
        return jsonify(ok=False, error="proxy_failed", detail=str(e)), 502

# ========= בריאות =========
@app.get("/healthz")
def healthz():
    return jsonify(ok=True, msg="proxy_ok", port=PORT), 200

@app.get("/ping")
def ping():
    return "pong", 200

# ========= ריצה מקומית =========
if __name__ == "__main__":
    print("\n[RUNPOD PROXY] ✅ Ready")
    print(f"[RUNPOD PROXY] 🌍 Local : http://127.0.0.1:{PORT}")
    print(f"[RUNPOD PROXY] 🔗 UI    : {CLOUD_PUBLIC_BASE}")
    print(f"[RUNPOD PROXY] 🔗 API   : {RUNPOD_BASE}")
    if RUNPOD_API_KEY and RUNPOD_API_KEY != "rpa_xxx":
        print(f"[RUNPOD PROXY] 🔐 Key   : {RUNPOD_API_KEY[:6]}...{RUNPOD_API_KEY[-5:]}")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
