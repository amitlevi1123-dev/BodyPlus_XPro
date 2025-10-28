# -*- coding: utf-8 -*-
"""
tools/test_runpod_live.py — בדיקת חיבור ל-RunPod
- שולח run-sync ומדפיס תשובה
- שולח run-submit ואז עושה polling לסטטוס עד סיום
"""

import time
import requests

API_KEY = "rpa_H63HWWYQPHFPTDDOY81DSRONUWZI0RAMOXE5B6P91rt4mu"
ENDPOINT_BASE = "https://api.runpod.ai/v2/1fmkdasa1l0x06"  # עדכן אם קיבלת ID אחר

headers_json = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
}

def run_sync(payload: dict):
    url = f"{ENDPOINT_BASE}/run-sync"
    resp = requests.post(url, headers=headers_json, json={"input": payload}, timeout=300)
    print("SYNC STATUS:", resp.status_code)
    print("SYNC BODY:", resp.text)

def run_submit_and_poll(payload: dict, poll_interval=2, max_wait=60):
    # submit
    url_submit = f"{ENDPOINT_BASE}/run"
    r = requests.post(url_submit, headers=headers_json, json={"input": payload}, timeout=60)
    print("SUBMIT STATUS:", r.status_code, "| BODY:", r.text)
    if r.status_code >= 300:
        return
    job = r.json()
    job_id = job.get("id") or job.get("jobId") or job.get("job_id")
    if not job_id:
        print("⚠️ לא נמצא job_id בתגובה.")
        return

    # poll
    url_status = f"{ENDPOINT_BASE}/status/{job_id}"
    t0 = time.time()
    while True:
        s = requests.get(url_status, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=30)
        try:
            body = s.json()
        except Exception:
            print("STATUS RAW:", s.text)
            break

        status = body.get("status")
        print(f"[{int(time.time()-t0)}s] STATUS:", status)

        if status in ("COMPLETED", "FAILED", "CANCELLED"):
            print("FINAL BODY:", body)
            break

        if time.time() - t0 > max_wait:
            print("⏳ timeout waiting for completion.")
            break

        time.sleep(poll_interval)

if __name__ == "__main__":
    # בדיקת SYNC (תוצאה חוזרת מיד)
    run_sync({"prompt": "Hello from BodyPlus_XPro SYNC"})

    print("\n" + "-"*60 + "\n")

    # בדיקת ASYNC + Polling
    run_submit_and_poll({"prompt": "Hello from BodyPlus_XPro ASYNC"}, poll_interval=2, max_wait=60)
