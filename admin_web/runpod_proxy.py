# -*- coding: utf-8 -*-
# admin_web/runpod_proxy.py — Proxy אחד ל-RunPod Serverless עם לוגים מפורטים
from flask import Flask, request, Response, jsonify
import os, json, time, traceback
import requests

# ===== תצורה =====
RUNPOD_BASE = (os.getenv("RUNPOD_BASE") or "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
API_KEY      = os.getenv("RUNPOD_API_KEY") or "rpa_JMCLGONT7MUZLIX6CXDZWLOSR8VAS3RMD1MVRL0A19qjux"  # עדיף דרך ENV
PORT         = int(os.getenv("PORT", "8000"))
DEBUG_LOG    = (os.getenv("PROXY_DEBUG", "1") == "1")       # שליטה על רעש לוגים (1=on)

app = Flask(__name__)

# ===== כלי לוג ותצוגה =====
def _now():
    return time.strftime("%H:%M:%S")

def _mask_key(k: str) -> str:
    if not k or k == "REPLACE_ME":
        return "(missing)"
    if len(k) < 12:
        return k[:3] + "..." + k[-3:]
    return k[:6] + "..." + k[-6:]

def _dump_headers(h: dict, limit=15) -> dict:
    out = {}
    i = 0
    for k, v in h.items():
        if k.lower() == "authorization":
            out[k] = "Bearer " + _mask_key(v.split()[-1])
        else:
            out[k] = v
        i += 1
        if i >= limit:
            out["..."] = f"+{len(h)-limit} more"
            break
    return out

def _body_snippet(raw: bytes, limit=600) -> str:
    try:
        s = raw.decode("utf-8", errors="replace")
    except Exception:
        return f"<{len(raw)} bytes>"
    return s if len(s) <= limit else s[:limit] + f"... (+{len(s)-limit} chars)"

def _log_incoming(tag: str):
    raw = request.get_data(cache=False, as_text=False) or b""
    print(f"[{_now()}] >>> {tag} {request.method} {request.path}?{request.query_string.decode(errors='ignore')}")
    print(f"[{_now()}]     headers: {json.dumps(_dump_headers(request.headers), ensure_ascii=False)}")
    if raw:
        print(f"[{_now()}]     body: { _body_snippet(raw) }")
    else:
        print(f"[{_now()}]     body: <empty>")
    print("", flush=True)

def _log_outgoing(url: str, payload):
    try:
        body_json = json.dumps(payload, ensure_ascii=False)
    except Exception:
        body_json = str(payload)
    print(f"[{_now()}]     → upstream URL: {url}")
    print(f"[{_now()}]     → payload: { _body_snippet(body_json.encode('utf-8')) }", flush=True)

def _log_response(resp: requests.Response):
    print(f"[{_now()}]     ← status: {resp.status_code}")
    print(f"[{_now()}]     ← headers: {json.dumps(_dump_headers(resp.headers), ensure_ascii=False)}")
    try:
        content = resp.content or b""
    except Exception:
        content = b"<unreadable>"
    print(f"[{_now()}]     ← body: { _body_snippet(content) }")
    print("", flush=True)

def _log_error(e: Exception):
    print(f"[{_now()}] !!! ERROR: {e}")
    tb = traceback.format_exc()
    print(tb, flush=True)

# ===== עזרי HTTP =====
def _auth_headers():
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept-Encoding": "identity",
    }

def _post(url: str, json_body: dict, timeout=(5, 300)) -> requests.Response:
    h = {"Content-Type": "application/json", **_auth_headers()}
    if DEBUG_LOG:
        _log_outgoing(url, json_body)
    return requests.post(url, headers=h, json=json_body, timeout=timeout)

def _get(url: str, timeout=(5, 60)) -> requests.Response:
    if DEBUG_LOG:
        print(f"[{_now()}]     → upstream GET: {url}", flush=True)
    return requests.get(url, headers=_auth_headers(), timeout=timeout)

def _require_key():
    if not API_KEY or API_KEY == "REPLACE_ME":
        return jsonify(ok=False, error="missing_api_key", hint="Set RUNPOD_API_KEY in environment"), 401

# ===== עמוד בית / סטטוס =====
@app.get("/")
def home():
    if DEBUG_LOG: _log_incoming("HOME")
    return jsonify(
        ok=True,
        msg="RunPod proxy alive. Use POST /run-submit (async) or /run-sync (sync).",
        upstream=RUNPOD_BASE,
        port=PORT,
        api_key_mask=_mask_key(API_KEY),
    ), 200

@app.get("/_proxy/health")
def proxy_health():
    if DEBUG_LOG: _log_incoming("HEALTH")
    ok = bool(RUNPOD_BASE) and bool(API_KEY) and API_KEY != "REPLACE_ME"
    return jsonify(ok=ok, upstream=RUNPOD_BASE, api_key_set=ok), (200 if ok else 503)

@app.get("/health")
def health_alias():
    if DEBUG_LOG: _log_incoming("HEALTH_ALIAS")
    return jsonify(ok=True), 200

@app.get("/_proxy/echo")
def echo_info():
    if DEBUG_LOG: _log_incoming("ECHO")
    info = {
        "method": request.method,
        "path": request.path,
        "args": request.args.to_dict(),
        "headers": _dump_headers(request.headers),
        "env": {
            "RUNPOD_BASE": RUNPOD_BASE,
            "PORT": PORT,
            "API_KEY_MASK": _mask_key(API_KEY),
        },
    }
    return jsonify(ok=True, info=info), 200

@app.get("/favicon.ico")
def fav():
    # למנוע ספאם בלוג
    return Response(status=204)

# ===== הרצות (SYNC / ASYNC / STATUS) =====
@app.post("/run-sync")
def run_sync():
    if DEBUG_LOG: _log_incoming("RUN_SYNC")
    need = _require_key()
    if need:
        return need
    body = request.get_json(silent=True) or {}
    try:
        url = f"{RUNPOD_BASE}/run-sync"
        resp = _post(url, {"input": body}, timeout=(5, 300))
        if DEBUG_LOG: _log_response(resp)
        return Response(
            resp.content,
            status=resp.status_code,
            headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
    except requests.RequestException as e:
        _log_error(e)
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

@app.post("/run-submit")
def run_submit():
    if DEBUG_LOG: _log_incoming("RUN_SUBMIT")
    need = _require_key()
    if need:
        return need
    body = request.get_json(silent=True) or {}
    try:
        url = f"{RUNPOD_BASE}/run"
        resp = _post(url, {"input": body})
        if DEBUG_LOG: _log_response(resp)
        return Response(
            resp.content,
            status=resp.status_code,
            headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
    except requests.RequestException as e:
        _log_error(e)
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

@app.get("/status/<job_id>")
def status(job_id: str):
    if DEBUG_LOG: _log_incoming("STATUS")
    need = _require_key()
    if need:
        return need
    try:
        url = f"{RUNPOD_BASE}/status/{job_id}"
        resp = _get(url)
        if DEBUG_LOG: _log_response(resp)
        return Response(
            resp.content,
            status=resp.status_code,
            headers={"Content-Type": resp.headers.get("Content-Type", "application/json")},
        )
    except requests.RequestException as e:
        _log_error(e)
        return jsonify(ok=False, error="upstream_request_failed", detail=str(e)), 502

# ===== חסימת סטרים שלא נתמך =====
@app.get("/video/stream.mjpg")
def no_stream():
    if DEBUG_LOG: _log_incoming("NO_STREAM")
    return jsonify(
        ok=False,
        error="serverless_no_stream",
        detail="Serverless לא תומך ב-MJPEG. השתמש ב-Pod או WebSocket."
    ), 400

# ===== הרצה =====
if __name__ == "__main__":
    print(f"🔁 Proxy running at http://127.0.0.1:{PORT} → {RUNPOD_BASE}")
    print(f"🔐 API key loaded? {_mask_key(API_KEY)}")
    print(f"🪵 DEBUG_LOG={DEBUG_LOG}")
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
