# admin_web/runpod_proxy.py — Proxy יחיד + UI בדיקה + לוגים מלאים
from __future__ import annotations
from flask import Flask, request, Response, jsonify, make_response
import os, json, time, traceback
import requests

# ========= קונפיג =========
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://1fmkdasa1l0x06.api.runpod.ai").rstrip("/")
API_KEY     = os.getenv("rpa_4PXVVU7WW1RON92M9VQTT5V2ZOA4T8FZMM68ZUOE0fsl21", "")  # ← בלי מפתח קשיח בקוד!
PORT        = int(os.getenv("PORT", "8000"))
DEBUG_LOG   = (os.getenv("PROXY_DEBUG", "1") == "1")      # 1=on, 0=off

_LAST = {"when": None, "path": None, "method": None, "status": None, "upstream": None,
         "resp_head": {}, "resp_text": None}

app = Flask(__name__)

# ========= עזרי לוג =========
def log(*args):
    if not DEBUG_LOG:
        return
    ts = time.strftime("[%H:%M:%S]")
    print(ts, *args, flush=True)

def _mask_key(k: str) -> str:
    if not k: return ""
    if len(k) <= 8: return "***"
    return f"{k[:6]}...{k[-5:]}"

def _short_headers(h: dict, drop=set(("cookie","authorization","x-api-key"))):
    out = {}
    for k,v in h.items():
        if k.lower() in drop:
            out[k] = "<hidden>"
        else:
            s = str(v)
            out[k] = s if len(s) < 200 else (s[:200] + " ...")
    return out

def _json_or_text(r: requests.Response) -> str:
    text = r.text
    return text if len(text) < 2000 else (text[:2000] + "\n... [truncated] ...")

# ========= עזרי HTTP =========
def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "Accept-Encoding": "identity"}

def _post(url: str, payload: dict, timeout=(5, 180)) -> requests.Response:
    h = {"Content-Type": "application/json", **_auth_headers()}
    return requests.post(url, json=payload, headers=h, timeout=timeout)

def _get(url: str, timeout=(5, 60)) -> requests.Response:
    return requests.get(url, headers=_auth_headers(), timeout=timeout)

# ========= CORS =========
@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

@app.route("/", methods=["OPTIONS"])
@app.route("/run-submit", methods=["OPTIONS"])
@app.route("/run-sync", methods=["OPTIONS"])
@app.route("/status/<job_id>", methods=["OPTIONS"])
def _opts(job_id=None):
    return Response(status=204)

# ========= דף בית / UI =========
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
<html lang="he"><head><meta charset="utf-8"><title>RunPod Proxy · UI</title>
<style>
body{{font-family:system-ui,Arial;margin:24px;line-height:1.5}}
.card{{border:1px solid #e5e7eb;border-radius:12px;padding:16px;max-width:860px}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0a0a0a;color:#e5e7eb;padding:12px;border-radius:8px;max-height:50vh;overflow:auto}}
label, input, button{{font-size:16px}}
input[type=text]{{width:420px}}
small{{color:#6b7280}}
</style>
</head>
<body>
  <h2>RunPod Proxy · UI בדיקה</h2>
  <div class="card">
    <p><b>Upstream:</b> {RUNPOD_BASE}<br><b>API Key:</b> {_mask_key(API_KEY)}</p>
    <p><label>Prompt: <input id="p" type="text" value="Hello from proxy"/></label>
       <button onclick="runSync()">Run Sync</button></p>
    <p><small>אם זה עובד, תראה גם לוגים ב־RunPod (Logs).</small></p>
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
      body: JSON.stringify({{prompt: document.getElementById('p').value}})
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

# ========= Health / Debug =========
@app.get("/_proxy/health")
def proxy_health():
    ok = bool(RUNPOD_BASE) and bool(API_KEY)
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=bool(API_KEY)), (200 if ok else 503)

@app.get("/_proxy/whoami")
def whoami():
    return jsonify(client_ip=request.remote_addr, method=request.method, path=request.path), 200

@app.get("/_proxy/last")
def last():
    return jsonify(_LAST), 200

@app.post("/_proxy/echo")
def echo():
    return jsonify(
        ok=True,
        headers=dict(request.headers),
        json=(request.get_json(silent=True) or {}),
        qs=request.args,
    ), 200

# ========= שמירת מפתח =========
def _require_key():
    if not API_KEY or API_KEY == "REPLACE_WITH_YOUR_KEY":
        return jsonify(ok=False, error="missing_api_key", hint="set RUNPOD_API_KEY env"), 401

# ========= נתיבים עיקריים =========
@app.post("/run-sync")
def run_sync():
    if (resp := _require_key()) is not None:
        return resp
    body = request.get_json(silent=True) or {}
    log(">>> /run-sync ←", json.dumps(body, ensure_ascii=False))
    try:
        t0 = time.time()
        up = f"{RUNPOD_BASE}/runsync"   # ← חשוב: runsync (ללא מקף)
        r  = _post(up, {"input": body})
        dt = int((time.time()-t0)*1000)
        text = _json_or_text(r)

        _LAST.update({
            "when": time.strftime("%Y-%m-%d %H:%M:%S"),
            "path": "/run-sync",
            "method": "POST",
            "status": r.status_code,
            "upstream": up,
            "resp_head": _short_headers(r.headers),
            "resp_text": text,
        })

        log(f"    → upstream {up} | HTTP {r.status_code} | {dt} ms")
        log("    resp.head:", json.dumps(_short_headers(r.headers), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(r.content, status=r.status_code,
                        headers={"Content-Type": r.headers.get("Content-Type","application/json")})
    except Exception as e:
        log("    EXC /run-sync:", repr(e))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

@app.post("/run-submit")
def run_submit():
    if (resp := _require_key()) is not None:
        return resp
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
            "resp_head": _short_headers(r.headers),
            "resp_text": text,
        })
        log(f"    → upstream {up} | HTTP {r.status_code}")
        log("    resp.head:", json.dumps(_short_headers(r.headers), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(r.content, status=r.status_code,
                        headers={"Content-Type": r.headers.get("Content-Type","application/json")})
    except Exception as e:
        log("    EXC /run-submit:", repr(e))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

@app.get("/status/<job_id>")
def status(job_id: str):
    if (resp := _require_key()) is not None:
        return resp
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
            "resp_head": _short_headers(r.headers),
            "resp_text": text,
        })
        log(f"    → upstream {up} | HTTP {r.status_code}")
        log("    resp.head:", json.dumps(_short_headers(r.headers), ensure_ascii=False))
        log("    resp.body:", text)
        return Response(r.content, status=r.status_code,
                        headers={"Content-Type": r.headers.get("Content-Type","application/json")})
    except Exception as e:
        log("    EXC /status:", repr(e))
        log(traceback.format_exc())
        return jsonify(ok=False, error="proxy_exception", detail=str(e)), 500

# חסימת סטרים – לא נתמך ב-Serverless
@app.get("/video/stream.mjpg")
def no_stream():
    return jsonify(ok=False, error="serverless_no_stream",
                   detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod."), 400

# ========= main =========
if __name__ == "__main__":
    print(f"🔁 Proxy running at http://127.0.0.1:{PORT} → {RUNPOD_BASE}")
    print(f"🔐 API key loaded? {_mask_key(API_KEY) if API_KEY else 'NO'}")
    print(f"🪵 DEBUG_LOG={'True' if DEBUG_LOG else 'False'}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
