# -*- coding: utf-8 -*-
"""
admin_web/runpod_proxy.py — Proxy + Full System Launcher (RunPod Ready)
-----------------------------------------------------------------------
מה הוא עושה?
• מספק Proxy ל-RunPod API (/run-sync, /run-submit, /status/<job_id>, /healthz)
• מרים את Flask Admin UI
• כשאנחנו בענן (RUNPOD=1 או RUNPOD_BASE עם api.runpod.ai) – מעלה את app/main.py ברקע
• מדפיס למסוף את כתובת ה-URL הציבורית (proxy.runpod.net) שתפתח בדפדפן
"""

from __future__ import annotations
from flask import Flask, request, Response, jsonify, make_response
import os, json, time, traceback, re, subprocess, sys, pathlib
import requests

# ========= קונפיג (ברירת מחדל; אפשר לדרוס ע"י משתני סביבה) =========
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY     = os.getenv("RUNPOD_API_KEY") or "rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21"
PORT        = int(os.getenv("PORT", "8000"))
DEBUG_LOG   = (os.getenv("PROXY_DEBUG", "1") == "1")  # 1=on, 0=off

app = Flask(__name__)

_LAST = {
    "when": None, "path": None, "method": None, "status": None,
    "upstream": None, "resp_head": {}, "resp_text": None
}

# ========= עזרי לוג =========
def log(*args):
    if not DEBUG_LOG:
        return
    ts = time.strftime("[%H:%M:%S]")
    print(ts, *args, flush=True)

def _mask_key(k: str) -> str:
    if not k:
        return ""
    return "***" if len(k) <= 8 else f"{k[:6]}...{k[-5:]}"

def _short_headers(h: dict, drop=None):
    if drop is None:
        drop = {"cookie", "authorization"}
    out = {}
    for k, v in h.items():
        out[k] = "<hidden>" if k.lower() in drop else (v if len(str(v)) < 200 else str(v)[:200] + " ...")
    return out

def _json_or_text(r: requests.Response) -> str:
    text = r.text
    return text if len(text) < 2000 else (text[:2000] + "\n... [truncated] ...")

# ========= עזרי HTTP ל-Upstream =========
def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Accept-Encoding": "identity"}

def _post(url: str, payload: dict, timeout=(5, 300)) -> requests.Response:
    h = {"Content-Type": "application/json", **_auth_headers()}
    return requests.post(url, json=payload, headers=h, timeout=timeout)

def _get(url: str, timeout=(5, 60)) -> requests.Response:
    return requests.get(url, headers=_auth_headers(), timeout=timeout)

# ========= CORS =========
@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.route("/", methods=["OPTIONS"])
@app.route("/run-submit", methods=["OPTIONS"])
@app.route("/run-sync", methods=["OPTIONS"])
@app.route("/status/<job_id>", methods=["OPTIONS"])
@app.route("/healthz", methods=["OPTIONS"])
def _opts(job_id=None):
    _ = job_id
    return Response(status=204)

# ========= דפי בית / UI =========
@app.get("/")
def home():
    payload = {
        "ok": True,
        "msg": "RunPod proxy alive. Use POST /run-submit (async) or /run-sync (sync).",
        "port": PORT,
        "upstream": RUNPOD_BASE,
        "api_key_mask": _mask_key(API_KEY),
    }
    log(">>> HOME GET /")
    log("    headers:", json.dumps(_short_headers(dict(request.headers)), ensure_ascii=False))
    return jsonify(payload), 200

@app.get("/ui")
def simple_ui():
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>RunPod Proxy · UI</title>
<style>
body{{font-family:system-ui,Arial;margin:24px;line-height:1.5}}
.card{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;max-width:860px}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0a0a0a;color:#e5e5e5;padding:12px;border-radius:8px;max-height:50vh;overflow:auto}}
label, input, button{{font-size:16px}}
input[type=text]{{width:420px}}
small{{color:#6b7280}}
</style>
</head>
<body>
  <h2>RunPod Proxy · Quick Test</h2>
  <div class="card">
    <p><b>Upstream:</b> {RUNPOD_BASE}<br><b>API Key:</b> {_mask_key(API_KEY)}</p>
    <p><label>Prompt: <input id="p" type="text" value="Hello from proxy"/></label>
       <button onclick="runSync()">Run Sync</button></p>
    <p><small>Run Sync does POST /run-sync and shows the raw response.</small></p>
    <pre id="out">—</pre>
  </div>
<script>
async function runSync(){{
  const out = document.getElementById('out');
  out.textContent = "⏳ Running /run-sync ...";
  try {{
    const r = await fetch('/run-sync', {{
      method:'POST',
      headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{ prompt: document.getElementById('p').value }})
    }});
    const text = await r.text();
    out.textContent = "HTTP "+r.status+"\\n\\n"+text;
  }} catch(e) {{
    out.textContent = "ERR: "+e;
  }}
}}
</script>
</body></html>"""
    return make_response(html, 200)

# ========= Health / WhoAmI / Last =========
@app.get("/healthz")
def healthz():
    return jsonify(ok=True, ts=time.time(), upstream=RUNPOD_BASE), 200

@app.get("/_proxy/whoami")
def whoami():
    return jsonify(client_ip=request.remote_addr, method=request.method, path=request.path), 200

@app.get("/_proxy/last")
def last():
    return jsonify(_LAST), 200

# ========= מגני קלט =========
def _require_key():
    if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
        return jsonify(ok=False, error="missing_api_key", hint="set RUNPOD_API_KEY env"), 401
    return None

# ========= נתיבים עיקריים =========
@app.post("/run-sync")
def run_sync():
    if (err_resp := _require_key()) is not None:
        return err_resp
    body = request.get_json(silent=True) or {}
    log(">>> /run-sync ←", json.dumps(body, ensure_ascii=False))
    try:
        t0 = time.time()
        up = f"{RUNPOD_BASE}/run-sync"
        r  = _post(up, {"input": body})
        dt = int((time.time() - t0) * 1000)
        text = _json_or_text(r)
        _LAST.update({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": "/run-sync",
            "method": "POST",
            "status": r.status_code,
            "upstream": up,
            "resp_head": _short_headers(dict(r.headers)),
            "resp_text": text,
        })
        log(f"    → upstream {up} | HTTP {r.status_code} | {dt} ms")
        log("    resp.head:", json.dumps(_short_headers(dict(r.headers)), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(
            r.content,
            status=r.status_code,
            headers={"Content-Type": r.headers.get("Content-Type", "application/json")},
        )
    except Exception as exc:
        log("    EXC /run-sync:", repr(exc))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(exc)), 500

@app.post("/run-submit")
def run_submit():
    if (err_resp := _require_key()) is not None:
        return err_resp
    body = request.get_json(silent=True) or {}
    log(">>> /run-submit ←", json.dumps(body, ensure_ascii=False))
    try:
        up = f"{RUNPOD_BASE}/run"
        r  = _post(up, {"input": body})
        text = _json_or_text(r)
        _LAST.update({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": "/run-submit",
            "method": "POST",
            "status": r.status_code,
            "upstream": up,
            "resp_head": _short_headers(dict(r.headers)),
            "resp_text": text,
        })
        log(f"    → upstream {up} | HTTP {r.status_code}")
        log("    resp.head:", json.dumps(_short_headers(dict(r.headers)), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(
            r.content,
            status=r.status_code,
            headers={"Content-Type": r.headers.get("Content-Type", "application/json")},
        )
    except Exception as exc:
        log("    EXC /run-submit:", repr(exc))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(exc)), 500

@app.get("/status/<job_id>")
def status(job_id: str):
    if (err_resp := _require_key()) is not None:
        return err_resp
    log(f">>> /status/{job_id}")
    try:
        up = f"{RUNPOD_BASE}/status/{job_id}"
        r  = _get(up)
        text = _json_or_text(r)
        _LAST.update({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": f"/status/{job_id}",
            "method": "GET",
            "status": r.status_code,
            "upstream": up,
            "resp_head": _short_headers(dict(r.headers)),
            "resp_text": text,
        })
        log(f"    → upstream {up} | HTTP {r.status_code}")
        log("    resp.head:", json.dumps(_short_headers(dict(r.headers)), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(
            r.content,
            status=r.status_code,
            headers={"Content-Type": r.headers.get("Content-Type", "application/json")},
        )
    except Exception as exc:
        log("    EXC /status:", repr(exc))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(exc)), 500

# חסימת סטרים – Serverless לא תומך MJPEG
@app.get("/video/stream.mjpg")
def no_stream():
    return jsonify(ok=False, error="serverless_no_stream",
                   detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod/שרת קבוע."), 400

# ========= עזרי ענן =========
def _abs(path: str) -> str:
    return str(pathlib.Path(path).resolve())

def _find_main_py() -> str:
    candidates = [
        "app/main.py",
        "/app/app/main.py",
        "/workspace/BodyPlus_XPro/app/main.py",
    ]
    for p in candidates:
        if pathlib.Path(p).exists():
            return p
    return "app/main.py"

def _endpoint_id_from_base(base: str) -> str | None:
    # https://api.runpod.ai/v2/<id>
    m = re.search(r"/v2/([a-zA-Z0-9]+)$", base.strip())
    return m.group(1) if m else None

def _public_url() -> str | None:
    # מחזיר את ה-URL הציבורי של RunPod Proxy לפי ה-endpoint id
    eid = _endpoint_id_from_base(RUNPOD_BASE)
    if not eid:
        return None
    return f"https://{eid}-8000.proxy.runpod.net"

def _launch_main_in_background():
    env = os.environ.copy()
    env.setdefault("NO_CAMERA", "1")   # אין מצלמה בענן
    env.setdefault("HEADLESS", "1")    # אל תפתח חלון (Tk)
    env.setdefault("POSE_ENABLE", "1")
    env.setdefault("OD_ENABLE", "1")
    env.setdefault("PYTHONUNBUFFERED", "1")

    main_py = _find_main_py()
    print(f"[RUNPOD] ▶ launching main.py inside server: {main_py}", flush=True)
    subprocess.Popen([sys.executable, _abs(main_py)], env=env, cwd=_abs("."))

# ========= main =========
if __name__ == "__main__":
    on_runpod = (os.getenv("RUNPOD") == "1") or RUNPOD_BASE.startswith("https://api.runpod.ai")

    if on_runpod:
        try:
            _launch_main_in_background()
        except Exception as e:
            print(f"[RUNPOD] !! failed to launch main.py: {e}", flush=True)

        pub = _public_url() or f"(set RUNPOD_BASE to see public URL)"
        print("[RUNPOD] ✅ Loaded Flask Admin UI (Dashboard + API)", flush=True)
        print(f"[RUNPOD] 🌍 Public URL: {pub}", flush=True)
        print(f"[RUNPOD]    Health: {pub}/healthz", flush=True)
        print(f"[RUNPOD]    UI    : {pub}/", flush=True)
        print(f"[RUNPOD] 🔗 Upstream: {RUNPOD_BASE}", flush=True)
        print(f"[RUNPOD] 🔐 API Key : {_mask_key(API_KEY)}", flush=True)
        print(f"[RUNPOD] 🚀 Listening on 0.0.0.0:{PORT}", flush=True)
        app.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)

    else:
        print(f"🔁 Proxy running at http://127.0.0.1:{PORT} → {RUNPOD_BASE}")
        print(f"🔐 API key loaded? {_mask_key(API_KEY) if API_KEY else 'NO'}")
        print(f"🪵 DEBUG_LOG={'True' if DEBUG_LOG else 'False'}")
        app.run(host="0.0.0.0", port=PORT, debug=True, threaded=True)
