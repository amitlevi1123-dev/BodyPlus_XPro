import requests, json
URL = "http://127.0.0.1:5000/run-sync"
payload = {"prompt":"Hello from LOCAL proxy"}
r = requests.post(URL, json=payload, timeout=60)
print("STATUS:", r.status_code)
print("TEXT:", r.text[:500])
