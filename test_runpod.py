# admin_web/mini_proxy_test.py
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.get("/")
def home():
    return jsonify(ok=True, msg="mini proxy alive"), 200

@app.get("/_proxy/health")
def health():
    return jsonify(ok=True, msg="health ok"), 200

@app.post("/run-sync")
def run_sync():
    data = request.get_json(silent=True) or {}
    # רק מחזיר מה שקיבלנו — כדי לבדוק שהראוט עובד
    return jsonify(ok=True, echo=data), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print(f"Running mini proxy on http://127.0.0.1:{port}")
    print("Routes:", app.url_map)  # הדפס רשימת ראוטים
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
