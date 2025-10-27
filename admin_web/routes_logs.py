# -*- coding: utf-8 -*-
# -------------------------------------------------------
# routes_logs.py — 🌐 API לוגים כ-Blueprint
# מחבר בין core/logs.py לבין ה-JS בדשבורד.
#
# נתיבים:
# • GET  /api/logs           → החזרת לוגים (אפשר since/level/limit)
# • GET  /api/logs/stream    → שידור חי (SSE) עם init/burst/ping_ms
# • POST /api/logs/clear     → ניקוי הזיכרון של הלוגים
# • GET  /api/logs/download  → הורדת הלוגים כקובץ טקסט
#
# הערות:
# - הפלט ב-/api/logs נשמר בפורמט {items, total, now} כדי לא לשבור את ה-UI.
# - מגבלות ופרמטרי ברירת מחדל נשלטים דרך ENV.
# -------------------------------------------------------

from __future__ import annotations
import os
import io
import json
import time
from typing import Any, Dict, List
from queue import Empty

from flask import Blueprint, Response, jsonify, request, send_file

# מבני נתונים ולוגר מגיעים מהשכבה המשותפת
from core.logs import LOG_BUFFER, LOG_QUEUE, logger

bp_logs = Blueprint("logs", __name__)

# --- קונפיג מה-ENV (עם ברירות מחדל זהות ל-server הישן) ---
LOGS_API_MAX_ITEMS   = int(os.getenv("LOGS_API_MAX_ITEMS", "400"))
LOG_STREAM_INIT_MAX  = int(os.getenv("LOG_STREAM_INIT_MAX", "50"))
LOG_STREAM_BURST_MAX = int(os.getenv("LOG_STREAM_BURST_MAX", "20"))
LOG_STREAM_PING_MS   = int(os.getenv("LOG_STREAM_PING_MS", "15000"))

# -------------------------------------------------------
# 📄 /api/logs — החזרת לוגים קיימים (עם סינון מאז timestamp)
# -------------------------------------------------------
@bp_logs.get("/api/logs")
def api_logs():
    """
    מחזיר לוגים, עם תמיכה בפרמטרים:
      - since / since_ts: unix ts צף (שניות) להחזרת חדשים בלבד
      - level: INFO/DEBUG/WARNING/ERROR (קייס-אינסנסיטיב)
      - max / limit: מספר מקסימלי של פריטים (חסום ל-LOGS_API_MAX_ITEMS)
    הפורמט נשמר: {items, total, now}
    """
    try:
        since = float(request.args.get("since") or request.args.get("since_ts") or 0.0)
    except ValueError:
        since = 0.0

    level = (request.args.get("level") or "").upper().strip()
    try:
        limit = int(request.args.get("max") or request.args.get("limit") or LOGS_API_MAX_ITEMS)
    except ValueError:
        limit = LOGS_API_MAX_ITEMS
    limit = max(1, min(limit, LOGS_API_MAX_ITEMS))

    buf_list: List[Dict[str, Any]] = list(LOG_BUFFER)
    items = [x for x in buf_list if x.get("ts", 0) > since and (not level or x.get("level") == level)]
    if len(items) > limit:
        items = items[-limit:]

    return jsonify(items=items, total=len(buf_list), now=time.time())

# -------------------------------------------------------
# 📡 /api/logs/stream — סטרימינג חי (SSE) עם באפר התחלתִי
# -------------------------------------------------------
@bp_logs.get("/api/logs/stream")
def api_logs_stream():
    """
    SSE stream של לוגים חיים.
    פרמטרים:
      - init: כמה פריטים אחרונים לשלוח מיד (<= LOG_STREAM_INIT_MAX)
      - burst: כמה פריטים לכל מחזור משיכה מהתור (<= LOG_STREAM_BURST_MAX, לפחות 1)
      - ping_ms: כל כמה מילישניות לשלוח :ping אם אין תנועה (>= 1000)
    """
    try:
        init = int(request.args.get("init") or LOG_STREAM_INIT_MAX)
    except Exception:
        init = LOG_STREAM_INIT_MAX
    init = max(0, min(init, LOG_STREAM_INIT_MAX))

    try:
        burst = int(request.args.get("burst") or LOG_STREAM_BURST_MAX)
    except Exception:
        burst = LOG_STREAM_BURST_MAX
    burst = max(1, min(burst, LOG_STREAM_BURST_MAX))

    try:
        ping_ms = int(request.args.get("ping_ms") or LOG_STREAM_PING_MS)
    except Exception:
        ping_ms = LOG_STREAM_PING_MS
    ping_ms = max(1000, ping_ms)

    def gen():
        # באפר פתיחה — שולחים n פריטים אחרונים כדי ליישר מצב לקוח
        if LOG_BUFFER and init:
            for item in list(LOG_BUFFER)[-init:]:
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        last_ping = time.time()
        while True:
            sent = 0
            try:
                timeout = max(0.1, ping_ms / 1000.0)
                while sent < burst:
                    item = LOG_QUEUE.get(timeout=timeout if sent == 0 else 0.001)
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                    sent += 1
                    last_ping = time.time()
            except Empty:
                # אין פריטים כרגע — שלח ping כדי לשמור חיבור חי לפי ping_ms
                if (time.time() - last_ping) * 1000.0 >= ping_ms:
                    yield ":ping\n\n"
                    last_ping = time.time()
            except GeneratorExit:
                break
            except Exception:
                # לא מפילים סטרים על חריגות מזדמנות
                pass

    return Response(gen(), mimetype="text/event-stream")

# -------------------------------------------------------
# 🧹 /api/logs/clear — ניקוי הלוגים
# -------------------------------------------------------
@bp_logs.post("/api/logs/clear")
def api_logs_clear():
    """
    מנקה את LOG_BUFFER ואת התור LOG_QUEUE.
    מחזיר ok=True וכמות פריטים שהתור ניקה כדי לעזור לדיאגנוסטיקה.
    """
    LOG_BUFFER.clear()
    cleared = 0
    while True:
        try:
            LOG_QUEUE.get_nowait()
            cleared += 1
        except Empty:
            break
    logger.info(f"LOGS CLEARED via /api/logs/clear (queue items cleared: {cleared})")
    return jsonify(ok=True, cleared_queue=cleared)

# -------------------------------------------------------
# 💾 /api/logs/download — הורדת הלוגים כקובץ טקסט
# -------------------------------------------------------
@bp_logs.get("/api/logs/download")
def api_logs_download():
    """
    יוצר קובץ טקסט מהלוגים בפורמט:
    [YYYY-MM-DD HH:MM:SS] [LEVEL] message
    """
    lines: List[str] = []
    now_fallback = time.time()
    for i in LOG_BUFFER:
        ts = i.get("ts", now_fallback)
        lvl = i.get("level", "INFO")
        msg = i.get("msg", "")
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        lines.append(f"[{t}] [{lvl}] {msg}")
    payload = "\n".join(lines).encode("utf-8")
    mem = io.BytesIO(payload)
    mem.seek(0)
    return send_file(
        mem,
        as_attachment=True,
        download_name="logs.txt",
        mimetype="text/plain; charset=utf-8",
    )
