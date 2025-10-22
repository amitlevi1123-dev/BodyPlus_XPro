# admin_web/routes_logs.py
# -------------------------------------------------------
# 🌐 API לוגים — מחבר בין core/logs.py לבין ה-JS בדשבורד
#
# מה הקובץ עושה:
# • /api/logs          → מחזיר את כל הלוגים (או חדשים מאז זמן מסוים)
# • /api/logs/stream   → שולח לוגים חיים בזמן אמת (SSE)
# • /api/logs/clear    → מוחק את הזיכרון של הלוגים
# • /api/logs/download → מאפשר להוריד את הלוגים כקובץ
#
# אין צורך לשנות כלום ב-JS — רק לוודא שהקובץ רשום ב-server.py
# -------------------------------------------------------

from __future__ import annotations
import json
import time
import io
from flask import Blueprint, Response, jsonify, send_file, request
from core.logs import LOG_BUFFER, LOG_QUEUE, logger

bp_logs = Blueprint("logs", __name__)

# -------------------------------------------------------
# 📄 /api/logs — החזרת לוגים קיימים
# -------------------------------------------------------

@bp_logs.get("/api/logs")
def api_logs():
    """מחזיר לוגים לפי timestamp (פרמטר 'since')"""
    try:
        since = float(request.args.get("since", 0))
    except ValueError:
        since = 0
    items = [i for i in LOG_BUFFER if i["ts"] > since]
    return jsonify({
        "items": items,
        "total": len(LOG_BUFFER),
        "now": time.time(),
    })

# -------------------------------------------------------
# 📡 /api/logs/stream — סטרימינג חי (SSE)
# -------------------------------------------------------

@bp_logs.get("/api/logs/stream")
def api_logs_stream():
    """שידור חי של לוגים בזמן אמת"""
    def gen():
        yield ":ok\n\n"  # שמירת חיבור פתוח
        while True:
            try:
                item = LOG_QUEUE.get(timeout=5)
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
            except Exception:
                yield ":ping\n\n"
    return Response(gen(), mimetype="text/event-stream")

# -------------------------------------------------------
# 🧹 /api/logs/clear — ניקוי הלוגים
# -------------------------------------------------------

@bp_logs.post("/api/logs/clear")
def api_logs_clear():
    """מוחק את הלוגים מהזיכרון"""
    LOG_BUFFER.clear()
    with LOG_QUEUE.mutex:
        LOG_QUEUE.queue.clear()
    logger.info("📭 LOGS CLEARED via /api/logs/clear")
    return jsonify({"status": "cleared"})

# -------------------------------------------------------
# 💾 /api/logs/download — הורדת הלוגים כקובץ
# -------------------------------------------------------

@bp_logs.get("/api/logs/download")
def api_logs_download():
    """מחזיר את הלוגים כקובץ טקסט להורדה"""
    text = "\n".join(
        f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(i['ts']))}] "
        f"[{i['level']}] {i['msg']}"
        for i in LOG_BUFFER
    )
    mem = io.BytesIO(text.encode("utf-8"))
    mem.seek(0)
    return send_file(
        mem,
        as_attachment=True,
        download_name="logs.txt",
        mimetype="text/plain",
    )
