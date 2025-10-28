# -*- coding: utf-8 -*-
"""
check_runpod_proxy.py — בדיקת פרוקסי ו-RunPod מקצה לקצה
1) קורא ENV: RUNPOD_BASE, RUNPOD_API_KEY, PORT (ברירת מחדל 5000)
2) בודק את הפרוקסי המקומי: / , /_proxy/health
3) שולח /run-sync דרך הפרוקסי ומדפיס תוצאה
4) שולח /run-submit דרך הפרוקסי, קורא /status/<id> עד תשובה
5) שולח /run-sync ישירות ל-RunPod (ללא פרוקסי) להשוואה
6) מדפיס סיכום ברור ושומר log לקובץ (check_runpod_proxy.log)
"""
from __future__ import annotations
import os, sys, time, json, traceback, datetime
from typing import Dict, Any
import requests

LOG_PATH = os.path.join(os.path.dirname(__file__), "check_runpod_proxy.log")

def log(*a):
    s = " ".join(str(x) for x in a)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {s}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def trunc(s: str, n: int = 300) -> str:
    s = s if isinstance(s, str) else str(s)
    return s if len(s) <= n else (s[:n] + "...")

def get_env(name: str, default: str = "") -> str:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v

def http_get(url: str, headers: Dict[str, str] | None = None, timeout=(5, 30)):
    return requests.get(url, headers=headers or {}, timeout=timeout)

def http_post(url: str, body: Dict[str, Any], headers: Dict[str, str] | None = None, timeout=(5, 120)):
    return requests.post(url, headers=headers or {}, json=body, timeout=timeout)

def must_ok(resp: requests.Response, ctx: str):
    if 200 <= resp.status_code < 300:
        return
    raise RuntimeError(f"{ctx} failed: HTTP {resp.status_code} | {trunc(resp.text)}")

def main():
    # ---------- Env ----------
    RUNPOD_BASE = get_env("RUNPOD_BASE", "https://api.runpod.ai/v2/1fmkdasa1l0x06").rstrip("/")
    API_KEY     = get_env("RUNPOD_API_KEY", "")
    PORT        = int(get_env("PORT", "5000"))
    HOST        = get_env("HOST", "127.0.0.1")
    PROXY_BASE  = f"http://{HOST}:{PORT}"

    # reset log
    try:
        open(LOG_PATH, "w", encoding="utf-8").close()
    except Exception:
        pass

    log("=== CHECK START ===")
    log("PROXY_BASE =", PROXY_BASE)
    log("RUNPOD_BASE =", RUNPOD_BASE)
    log("API_KEY set? ", bool(API_KEY))

    summary = {"proxy_home": False, "proxy_health": False, "sync_via_proxy": False,
               "submit_status_via_proxy": False, "sync_direct_runpod": False}

    # ---------- 1) Proxy home ----------
    try:
        r = http_get(f"{PROXY_BASE}/")
        must_ok(r, "GET /")
        summary["proxy_home"] = True
        log("OK / →", trunc(r.text))
    except Exception as e:
        log("ERR / →", e)

    # ---------- 2) Proxy detailed health ----------
    try:
        r = http_get(f"{PROXY_BASE}/_proxy/health")
        must_ok(r, "GET /_proxy/health")
        log("OK /_proxy/health →", trunc(r.text))
        summary["proxy_health"] = True
    except Exception as e:
        log("ERR /_proxy/health →", e)

    # ---------- 3) /run-sync via proxy ----------
    try:
        payload = {"probe": "sync_via_proxy", "ts": time.time()}
        r = http_post(f"{PROXY_BASE}/run-sync", {"prompt": "Hello via proxy", "meta": payload})
        must_ok(r, "POST /run-sync (proxy)")
        log("OK /run-sync (proxy) →", trunc(r.text))
        summary["sync_via_proxy"] = True
    except Exception as e:
        log("ERR /run-sync (proxy) →", e)

    # ---------- 4) /run-submit via proxy and poll /status ----------
    try:
        r = http_post(f"{PROXY_BASE}/run-submit", {"prompt": "Hello async via proxy", "ts": time.time()})
        must_ok(r, "POST /run-submit (proxy)")
        data = {}
        try:
            data = r.json()
        except Exception:
            pass
        job_id = (data.get("id") or data.get("jobId") or "").strip()
        if not job_id:
            raise RuntimeError(f"run-submit returned no job id. Raw: {trunc(r.text)}")
        log("SUBMITTED job id:", job_id)

        # poll status
        deadline = time.time() + 90
        last_status = "UNKNOWN"
        while time.time() < deadline:
            rs = http_get(f"{PROXY_BASE}/status/{job_id}")
            must_ok(rs, "GET /status/<id> (proxy)")
            try:
                j = rs.json()
            except Exception:
                j = {}
            last_status = j.get("status") or j.get("state") or ""
            log("STATUS:", last_status, trunc(rs.text, 200))
            if last_status and last_status.upper() not in ("IN_QUEUE", "IN_PROGRESS", "PENDING"):
                break
            time.sleep(2)

        if not last_status:
            raise RuntimeError("Empty status")
        summary["submit_status_via_proxy"] = True
    except Exception as e:
        log("ERR submit/status (proxy) →", e)

    # ---------- 5) Direct /run-sync to RunPod (no proxy) ----------
    try:
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json", "Accept-Encoding": "identity"}
        body = {"input": {"probe": "sync_direct_runpod", "ts": time.time(), "prompt": "Hello direct"}}
        r = requests.post(f"{RUNPOD_BASE}/run-sync", headers=headers, json=body, timeout=(5, 180))
        must_ok(r, "POST /run-sync (direct)")
        log("OK /run-sync (direct) →", trunc(r.text))
        summary["sync_direct_runpod"] = True
    except Exception as e:
        log("ERR /run-sync (direct) →", e)

    # ---------- Summary ----------
    log("=== SUMMARY ===")
    for k, v in summary.items():
        log(f"{k:>24}: {'PASS' if v else 'FAIL'}")

    # exit code by result
    fails = [k for k, v in summary.items() if not v]
    if fails:
        log("FAILED checks:", ", ".join(fails))
        sys.exit(2)
    log("ALL CHECKS PASSED")
    sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        log("FATAL:", traceback.format_exc())
        sys.exit(3)
