# -*- coding: utf-8 -*-
"""
server.py — Admin UI + API (גרסה רזה, ללא video_manager)
--------------------------------------------------------
• Flask (דשבורד, לוגים, וידאו) — /video/stream.mjpg
• /payload מעדיף admin_web.state; אחרת LAST_PAYLOAD המקומי
• סטרים MJPEG מגיע דרך admin_web.routes_video (ingest/streamer)
• ObjDet ב-blueprint נפרד (routes_objdet.py)
• תרגילים: /api/exercise/*

כולל:
- ProxyFix (לעבודה תקינה מאחורי Reverse Proxy)
- /capture (דף לפתיחת מצלמה בדפדפן ושידור ל-ingest)
- /version, /healthz, /readyz
- הגשה דחוסה מראש לקבצי UI (html/js/css.gz)

שימו לב:
- /api/exercise/simulate תומך בשני מצבים:
  1) ברירת מחדל: מחזיר sets/reps (תואם בדיקות).
  2) אם as="report" או full_report=true: מחזיר דו״ח מלא (build_simulated_report).
"""

from __future__ import annotations
import os, json, math, time, threading, logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from queue import Empty
from urllib.parse import parse_qs

from flask import (
    Flask, Response, jsonify, render_template, request, send_from_directory,
    stream_with_context, redirect, url_for, send_file, make_response
)
from werkzeug.middleware.proxy_fix import ProxyFix

# === וידאו — חובה שה-BP ייטען (ingest/MJPEG/HUD) ===
from admin_web.routes_video import video_bp  # וידאו בנתיב שביקשת

# === Blueprint לטאב "העלאת וידאו" (אם קיים בפרויקט) ===
try:
    from admin_web.routes_upload_video import upload_video_bp
except Exception:
    upload_video_bp = None  # type: ignore

# === Action Bus + State (אם קיימים) ===
try:
    from admin_web.routes_actions import actions_bp, state_bp
except Exception:
    actions_bp = None  # type: ignore
    state_bp = None  # type: ignore

# (אופציונלי) worker למדידות וידאו
try:
    from app.ui.video_metrics_worker import start_video_metrics_worker
except Exception:
    start_video_metrics_worker = None  # type: ignore

# ===== לוגים / באפר =====
try:
    from core.logs import setup_logging, logger, LOG_BUFFER, LOG_QUEUE
except Exception:
    import collections, queue
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("server")
    LOG_BUFFER = collections.deque(maxlen=2000)
    LOG_QUEUE = queue.Queue()

# ===== גרסת payload =====
try:
    from core.payload import PAYLOAD_VERSION
except Exception:
    PAYLOAD_VERSION = "1.2.0"

# ===== payload משותף (אם יש main/state) =====
try:
    from admin_web.state import get_payload as get_shared_payload  # type: ignore
except Exception:
    def get_shared_payload() -> Dict[str, Any]:
        return {}

# ===== ObjDet status (אם יש) =====
try:
    from admin_web.routes_objdet import OBJDET_STATUS, OBJDET_STATUS_LOCK  # type: ignore
except Exception:
    import threading as _th
    OBJDET_STATUS = {"ok": False, "note": "objdet_status_unavailable"}
    OBJDET_STATUS_LOCK = _th.Lock()

def _import_get_streamer():
    # נסה קודם app.ui.video, ואם לא — מה-BP של הווידאו
    try:
        from app.ui.video import get_streamer as f  # type: ignore
        return f
    except Exception:
        pass
    try:
        from admin_web.routes_video import get_streamer as f  # type: ignore
        return f
    except Exception:
        pass
    return lambda: None

# ===== ניטור מערכת (אופציונלי) =====
try:
    from core.system.monitor import get_snapshot
except Exception:
    def get_snapshot() -> Dict[str, Any]:
        return {"ok": False, "error": "system_monitor_unavailable"}

# ===== Exercise Analyzer (אופציונלי) =====
try:
    from admin_web.exercise_analyzer import (
        analyze_exercise, simulate_exercise, sanitize_metrics_payload,
        build_simulated_report,  # ← חדש: דו״ח סימולציה מלא
    )  # type: ignore
except Exception as _e:
    logger.warning(f"[EXR] analyzer import failed: {_e}")
    analyze_exercise = None  # type: ignore
    simulate_exercise = None  # type: ignore
    sanitize_metrics_payload = None  # type: ignore
    build_simulated_report = None  # type: ignore

# ===== Exercise Engine (אופציונלי) =====
try:
    from exercise_engine.runtime.runtime import run_once as exr_run_once
    from exercise_engine.runtime.engine_settings import SETTINGS as EXR_SETTINGS
    from exercise_engine.registry.loader import load_library as exr_load_library
    _EXR_OK = True
except Exception as _e:
    logger.warning(f"[EXR] engine imports failed: {_e}")
    _EXR_OK = False

try:
    from exercise_engine.runtime import log as exlog
    _EXLOG_OK = True
except Exception:
    _EXLOG_OK = False

# =================== קונפיג כללי ===================
APP_VERSION = os.getenv("APP_VERSION", "dev")
GIT_COMMIT  = os.getenv("GIT_COMMIT", "")[:12] or None
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "").strip()
ENABLE_HEARTBEAT = os.getenv("ENABLE_HEARTBEAT", "1") == "1"
HEARTBEAT_INTERVAL_SEC = float(os.getenv("HEARTBEAT_INTERVAL_SEC", "30"))

LOGS_API_MAX_ITEMS   = int(os.getenv("LOGS_API_MAX_ITEMS", "400"))
LOG_STREAM_INIT_MAX  = int(os.getenv("LOG_STREAM_INIT_MAX", "50"))
LOG_STREAM_BURST_MAX = int(os.getenv("LOG_STREAM_BURST_MAX", "20"))
LOG_STREAM_PING_MS   = int(os.getenv("LOG_STREAM_PING_MS", "15000"))

EXR_DIAG_INIT_MAX  = int(os.getenv("EXR_DIAG_INIT_MAX", "100"))
EXR_DIAG_BURST_MAX = int(os.getenv("EXR_DIAG_BURST_MAX", "20"))
EXR_DIAG_PING_MS   = int(os.getenv("EXR_DIAG_PING_MS", "10000"))

BASE_DIR      = Path(__file__).resolve().parent
TPL_DIR       = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"
LEGACY_IMAGES = BASE_DIR / "images"

_now_ms = lambda: int(time.time() * 1000)

# ===== מחסן payload מקומי (אם אין main/state) =====
LAST_PAYLOAD_LOCK = threading.Lock()
LAST_PAYLOAD: Optional[Dict[str, Any]] = None

# ===== Cache למנוע תרגילים (אופציונלי) =====
ENGINE_LIB_LOCK = threading.Lock()
ENGINE_LIB = {"lib": None, "root": str((Path(__file__).resolve().parent / "exercise_library"))}

def _get_engine_library():
    if not _EXR_OK:
        raise RuntimeError("exercise engine not available")
    if ENGINE_LIB["lib"] is not None:
        return ENGINE_LIB["lib"]
    with ENGINE_LIB_LOCK:
        if ENGINE_LIB["lib"] is not None:
            return ENGINE_LIB["lib"]
        lib_dir = Path(ENGINE_LIB["root"])
        lib = exr_load_library(lib_dir)
        logger.info(f"[EXR] library loaded @ {lib_dir} (version: {getattr(lib, 'version', 'unknown')})")
        ENGINE_LIB["lib"] = lib
        return lib

LAST_EXERCISE_REPORT_LOCK = threading.Lock()
LAST_EXERCISE_REPORT: Optional[Dict[str, Any]] = None

# =================== Anti-spam ללוגים ===================
_OD1502_STATE = {"sig": None, "count": 0, "last": 0.0}
def _dedup_od1502(title: str, detail: Any = None, level: str = "debug"):
    try:
        now = time.time()
        sig = (title, json.dumps(detail, sort_keys=True, ensure_ascii=False) if detail is not None else None)
        if (_OD1502_STATE["sig"] != sig) or (now - _OD1502_STATE["last"] > 5.0):
            cnt = _OD1502_STATE["count"]
            _OD1502_STATE.update({"sig": sig, "count": 0, "last": now})
            msg = f"OD1502 {title}"
            if detail is not None:
                msg += f" | detail={detail!r}"
            if cnt:
                msg += f" | suppressed={cnt}"
            lf = {"debug": logger.debug, "warning": logger.warning, "error": logger.error}.get(level, logger.debug)
            lf(msg)
        else:
            _OD1502_STATE["count"] += 1
    except Exception:
        pass

# =================== Helpers ===================
def _background_log_heartbeat() -> None:
    i = 0
    while True:
        time.sleep(max(1.0, HEARTBEAT_INTERVAL_SEC))
        i += 1
        try:
            logger.debug(f"heartbeat #{i} (server.py)")
        except Exception:
            pass

def _flatten_dict(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        nk = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten_dict(v, nk))
        else:
            out[nk] = v
    return out

def _get_empty_objdet_payload() -> Dict[str, Any]:
    return {
        "frame": {"w": 1280, "h": 720, "mirrored": False, "ts_ms": _now_ms()},
        "objects": [], "tracks": [],
        "detector_state": {"ok": False, "err": "no_detection_engine", "provider": "none", "fps": 0.0},
    }

def normalize_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    res: Dict[str, Any] = {"metrics": [], "ts": time.time()}
    m = raw.get("metrics")
    metrics_list: List[Dict[str, Any]] = []
    if isinstance(m, list):
        for item in m:
            if isinstance(item, dict) and "name" in item:
                metrics_list.append({
                    "name": item.get("name", ""), "value": item.get("value", ""),
                    "unit": item.get("unit", ""), "stale": bool(item.get("stale", False)),
                })
    elif isinstance(m, dict):
        flat = _flatten_dict(m)
        for k, v in flat.items():
            try: val = float(v)
            except Exception: val = v
            metrics_list.append({"name": k, "value": val, "unit": "", "stale": False})
    else:
        flat = _flatten_dict(raw) if isinstance(raw, dict) else {}
        for drop in ("hands", "hand_orientations", "categories", "ts"):
            flat.pop(drop, None)
        for k, v in flat.items():
            try: val = float(v)
            except Exception: val = v
            metrics_list.append({"name": k, "value": val, "unit": "", "stale": False})
    res["metrics"] = metrics_list
    if isinstance(raw.get("ts"), (int, float)):
        res["ts"] = float(raw["ts"])
    return res

# ---------- פרסינג סלחני לגוף לא-JSON ----------
def _coerce_scalar(x):
    if isinstance(x, list) and len(x) == 1:
        x = x[0]
    if isinstance(x, str):
        t = x.strip().lower()
        if t in ("true", "false"):
            return t == "true"
        try:
            if "." in t:
                return float(t)
            return int(t)
        except Exception:
            return x
    return x

def _try_parse_non_json_body(raw: str):
    if not raw or not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        q = parse_qs(raw, keep_blank_values=True, strict_parsing=False)
        if not q:
            return None
        out = {k: _coerce_scalar(v) for k, v in q.items()}
        if isinstance(out.get("detections"), str):
            try:
                out["detections"] = json.loads(out["detections"])
            except Exception:
                pass
        return out
    except Exception:
        return None

# ---------- תיקוני סכימה בצד השרת ----------
def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)

def _sanitize_numbers_inplace(obj: Any):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            obj[k] = _sanitize_numbers_inplace(v)
        return obj
    if isinstance(obj, list):
        return [_sanitize_numbers_inplace(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)
    return obj

def _ensure_ts_frameid(d: Dict[str, Any]) -> None:
    if "ts" not in d:
        ts_ms = d.get("ts_ms")
        if _finite(ts_ms):
            d["ts"] = float(ts_ms) / 1000.0
        else:
            d["ts"] = time.time()
    if "frame_id" not in d:
        frm = d.get("frame")
        if isinstance(frm, dict) and _finite(frm.get("frame_id")):
            d["frame_id"] = int(frm["frame_id"])
        else:
            d["frame_id"] = 0

def _ensure_detections_from_objdet(d: Dict[str, Any]) -> None:
    if "detections" in d and isinstance(d["detections"], list):
        return
    dets: List[Dict[str, Any]] = []
    objs = d.get("objdet", {}).get("objects") if isinstance(d.get("objdet"), dict) else None
    if isinstance(objs, list):
        for o in objs:
            if not isinstance(o, dict):
                continue
            bbox = o.get("bbox"); conf = o.get("conf")
            bb = None
            try:
                if isinstance(bbox, dict):
                    x = bbox.get("x", bbox.get("x1")); y = bbox.get("y", bbox.get("y1"))
                    w = bbox.get("w"); h = bbox.get("h")
                    if _finite(x) and _finite(y) and _finite(w) and _finite(h):
                        bb = [float(x), float(y), float(x + w), float(y + h)]
                    else:
                        x1 = bbox.get("x1"); y1 = bbox.get("y1"); x2 = bbox.get("x2"); y2 = bbox.get("y2")
                        if all(_finite(v) for v in (x1, y1, x2, y2)):
                            bb = [float(x1), float(y1), float(x2), float(y2)]
                elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, a, b = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                    bb = [x1, y1, x1 + a, y1 + b] if a > 0 and b > 0 else [x1, y1, a, b]
            except Exception:
                bb = None
            item: Dict[str, Any] = {}
            if isinstance(conf, (int, float)) and math.isfinite(float(conf)):
                item["conf"] = float(conf)
            if isinstance(bb, list) and len(bb) == 4 and all(_finite(v) for v in bb):
                item["bbox"] = [float(v) for v in bb]
            if item:
                dets.append(item)
    d["detections"] = dets

def _server_side_schema_fixups(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict):
        return d
    _ensure_ts_frameid(d)
    _ensure_detections_from_objdet(d)
    _sanitize_numbers_inplace(d)
    return d

# ------------------ זמן עליית שרת ------------------
START_TS = time.time()

# =================== Flask App ===================
def create_app() -> Flask:
    try:
        setup_logging()
    except Exception:
        pass

    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    TPL_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    app = Flask(
        __name__,
        template_folder=str(TPL_DIR),
        static_folder=str(STATIC_DIR),
        static_url_path="/static",
    )

    # מאחורי פרוקסי (HTTPS/Host/Prefix)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    if ENABLE_HEARTBEAT:
        threading.Thread(target=_background_log_heartbeat, daemon=True).start()

    # --- רישום blueprints ---
    app.register_blueprint(video_bp)
    logger.info("[Server] Registered video_bp blueprint")

    if upload_video_bp is not None:
        app.register_blueprint(upload_video_bp)
        logger.info("[Server] Registered upload_video_bp blueprint")

    if actions_bp is not None:
        app.register_blueprint(actions_bp)
        logger.info("[Server] Registered actions_bp (/api/action)")

    if state_bp is not None:
        app.register_blueprint(state_bp)
        logger.info("[Server] Registered state_bp (/api/video/state)")

    try:
        from admin_web.routes_objdet import objdet_bp
        app.register_blueprint(objdet_bp)
        logger.info("[Server] Registered objdet_bp blueprint")
    except Exception:
        pass

    if callable(start_video_metrics_worker):
        try:
            start_video_metrics_worker()
            logger.info("[VideoWorker] video_metrics_worker started")
        except Exception as e:
            logger.warning(f"[VideoWorker] failed to start: {e}")

    logger.info("=== Admin UI (Flask – Single server) ===")
    logger.info(f"APP_VERSION={APP_VERSION}  DEFAULT_BACKEND={DEFAULT_BACKEND or '(none)'}")

    # ---------------- Rate-limit ל-start/stop (פר-IP) ----------------
    from time import time as _now
    _RL_GAP = float(os.getenv("VIDEO_RATE_LIMIT_SEC", "3.0"))
    _RL_PATHS = {"/api/video/start", "/api/video/stop"}
    _RL_STATE: Dict[str, Dict[str, float]] = {p: {} for p in _RL_PATHS}

    @app.before_request
    def _throttle_video_start_stop():
        try:
            if request.path not in _RL_PATHS or request.method != "POST":
                return None
            ip = (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "0.0.0.0").split(",")[0].strip()
            now = _now()
            last = _RL_STATE[request.path].get(ip, 0.0)
            if (now - last) < _RL_GAP:
                retry = max(0.0, _RL_GAP - (now - last))
                return jsonify({"ok": False, "error": "too_fast", "retry_after_sec": round(retry, 2)}), 429
            _RL_STATE[request.path][ip] = now
        except Exception:
            pass
        return None

    @app.after_request
    def _no_cache(resp: Response):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return resp

    @app.context_processor
    def _inject():
        def has_endpoint(name: str) -> bool:
            return name in app.view_functions
        def url_for_safe(name: str, **kwargs) -> str:
            return url_for(name, **kwargs) if name in app.view_functions else "#"
        return {
            "app_endpoints": set(app.view_functions.keys()),
            "has_endpoint": has_endpoint,
            "url_for_safe": url_for_safe,
            "app_version": APP_VERSION,
        }

    # ---------------- UI: עדיפות להגשת SPA מ-static (כולל קבצים דחוסים מראש) ----------------
    def _serve_gz_or_plain(path_no_gz: Path, default_mime: str) -> Response:
        gz = path_no_gz.with_suffix(path_no_gz.suffix + ".gz")
        if gz.exists():
            resp = make_response(send_file(gz, mimetype=default_mime))
            resp.headers["Content-Encoding"] = "gzip"
            return resp
        return send_file(path_no_gz, mimetype=default_mime)

    @app.get("/")
    def root_index():
        idx = STATIC_DIR / "index.html"
        if idx.exists() or idx.with_suffix(".html.gz").exists():
            return _serve_gz_or_plain(idx, "text/html")
        return redirect(url_for("dashboard"))

    @app.get("/ui")
    def ui_index():
        idx = STATIC_DIR / "index.html"
        if idx.exists() or idx.with_suffix(".html.gz").exists():
            return _serve_gz_or_plain(idx, "text/html")
        return redirect(url_for("dashboard"))

    @app.get("/ui/<path:filename>")
    def ui_static(filename: str):
        p = STATIC_DIR / filename
        # תמיכה בקבצי JS/CSS דחוסים מראש
        if not p.exists() and not filename.endswith(".gz"):
            gz = STATIC_DIR / (filename + ".gz")
            if gz.exists():
                mime = "application/octet-stream"
                if filename.endswith(".js"):
                    mime = "application/javascript"
                elif filename.endswith(".css"):
                    mime = "text/css"
                elif filename.endswith(".html"):
                    mime = "text/html"
                resp = make_response(send_file(gz, mimetype=mime))
                resp.headers["Content-Encoding"] = "gzip"
                return resp
        return send_from_directory(str(STATIC_DIR), filename)

    # ---- דפי תבניות (Jinja) ----
    @app.route("/dashboard", methods=["GET"])
    def dashboard():
        return render_template("dashboard.html", active_page="dashboard", app_version=APP_VERSION)

    @app.route("/metrics", methods=["GET"])
    def metrics_page():
        return render_template("metrics.html", active_page="metrics_page", app_version=APP_VERSION)

    @app.route("/logs", methods=["GET"])
    def logs_page():
        return render_template("logs.html", active_page="logs_page", app_version=APP_VERSION)

    @app.route("/compare", methods=["GET"])
    def compare_page():
        return render_template("compare.html", active_page="compare_page", app_version=APP_VERSION)

    @app.route("/video", methods=["GET"])
    def video_page():
        return render_template("video.html", active_page="video_page", app_version=APP_VERSION)

    @app.route("/settings", methods=["GET"])
    def settings_page():
        return render_template("settings.html", active_page="settings_page", app_version=APP_VERSION)

    @app.route("/object-detection", endpoint="object_detection_page", methods=["GET"])
    def object_detection_page():
        return render_template("object_detection.html", active_page="object_detection_page",
                               page_title="Object Detection", app_version=APP_VERSION)

    @app.route("/exercise", endpoint="exercise_page", methods=["GET"])
    def exercise_page():
        try:
            return render_template("exercise.html", active_page="exercise_page",
                                   page_title="זיהוי תרגיל", app_version=APP_VERSION)
        except Exception as e:
            logger.warning(f"/exercise fallback (template missing?): {e}")
            html = """
            <!doctype html><meta charset='utf-8'>
            <title>Exercise (fallback)</title>
            <style>body{font-family:system-ui,Segoe UI,Arial;margin:2rem}code{background:#f3f3f3;padding:.2rem .4rem}</style>
            <h1>Exercise – Fallback</h1>
            <p>תבנית <code>templates/exercise.html</code> לא נמצאה/קרסה. אפשר להמשיך לעבוד בדפים אחרים.</p>
            """
            return Response(html, mimetype="text/html")

    @app.route("/system", methods=["GET"])
    def system_page():
        return render_template("system.html", active_page="system_page", app_version=APP_VERSION)

    # ---- דף פתיחת מצלמה בדפדפן (ingest) ----
    @app.get("/capture")
    def capture_page():
        return render_template("capture.html")

    @app.route("/static/", methods=["GET"])
    def static_index():
        return Response("", status=204)

    if LEGACY_IMAGES.exists():
        @app.route("/images/<path:filename>", methods=["GET"])
        def legacy_images(filename: str):
            return send_from_directory(str(LEGACY_IMAGES), filename)

    # ---- בריאות/מערכת ----
    @app.get("/version")
    def version():
        up = max(0.0, time.time() - START_TS)
        return jsonify({
            "app_version": APP_VERSION,
            "git_commit": GIT_COMMIT,
            "payload_version": PAYLOAD_VERSION,
            "uptime_sec": round(up, 1),
            "env": {"runpod": bool(os.getenv("RUNPOD_BASE"))}
        }), 200

    @app.get("/healthz")
    def healthz():
        try:
            snap = {}
            try:
                snap = get_snapshot() or {}
            except Exception:
                snap = {}

            payload = {}
            try:
                payload = get_shared_payload() or {}
            except Exception:
                payload = {}
            if not payload and isinstance(LAST_PAYLOAD, dict):
                payload = LAST_PAYLOAD or {}
            now = time.time()
            ts = float(payload.get("ts", now))
            age = max(0.0, now - ts)

            # וידאו
            opened = running = False
            gs = _import_get_streamer()
            if callable(gs):
                s = gs()
                opened = bool(getattr(s, "is_open", lambda: False)())
                running = bool(getattr(s, "is_running", lambda: False)())

            gpu_av = bool((snap.get("gpu") or {}).get("available", False))
            ok = (age < 3.0)  # קריטריון פשוט
            return jsonify({
                "ok": ok,
                "payload": {"age_sec": round(age, 3), "present": bool(payload)},
                "video": {"opened": opened, "running": running},
                "gpu": {"available": gpu_av},
                "system": {"ok": bool(snap.get("ok", True))},
                "ts": int(now)
            }), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 200

    @app.get("/readyz")
    def readyz():
        try:
            t_ok = TPL_DIR.exists()
            s_ok = STATIC_DIR.exists()
            snap_ok = True
            try:
                s = get_snapshot()
                if isinstance(s, dict) and s.get("error"):
                    snap_ok = False
            except Exception:
                snap_ok = False

            gs = _import_get_streamer()
            streamer_ok = callable(gs)

            ok = all([t_ok, s_ok, snap_ok, streamer_ok])
            code = 200 if ok else 503
            return jsonify({
                "ok": ok, "templates": t_ok, "static": s_ok,
                "system_monitor": snap_ok, "streamer_available": streamer_ok
            }), code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 503

    @app.route("/api/health", methods=["GET"])
    def api_health():
        return jsonify(ok=True, version=APP_VERSION, uptime_sec=round(time.time() - START_TS, 1)), 200

    @app.route("/api/system", methods=["GET"])
    def api_system():
        try:
            return jsonify(get_snapshot())
        except Exception:
            logger.exception("Error in /api/system")
            return jsonify({"ok": False, "error": "system_api failure"}), 500

    # ---- payload ----
    @app.route("/payload", methods=["GET"])
    def payload_route():
        try:
            shared = get_shared_payload()
            if isinstance(shared, dict) and shared:
                out = dict(shared)
                out.setdefault("objdet", _get_empty_objdet_payload())
                out.setdefault("payload_version", PAYLOAD_VERSION)
                return jsonify(out)
            with LAST_PAYLOAD_LOCK:
                live = LAST_PAYLOAD.copy() if isinstance(LAST_PAYLOAD, dict) else None
            if isinstance(live, dict) and live:
                out = dict(live)
                out.setdefault("objdet", _get_empty_objdet_payload())
                out.setdefault("payload_version", PAYLOAD_VERSION)
                return jsonify(out)
            out = {"frame": {"w": None, "h": None, "ts_ms": 0, "mirrored": False},
                   "mp": {"landmarks": []}, "metrics": {},
                   "objdet": _get_empty_objdet_payload(),
                   "ts": time.time(), "payload_version": PAYLOAD_VERSION}
            return jsonify(out)
        except Exception:
            logger.exception("Error in /payload")
            return jsonify({"ok": False, "error": "payload_route failure",
                            "objdet": _get_empty_objdet_payload(),
                            "payload_version": PAYLOAD_VERSION}), 500

    # ---- קבלת payload חיצוני (OD) ----
    REQUIRED_KEYS = ("detections",)
    MAX_DETS = int(os.getenv("MAX_DETECTIONS", "500"))

    def _is_finite_number(x: Any) -> bool:
        return isinstance(x, (int, float)) and math.isfinite(x)

    def _validate_od_payload(d: Any):
        if not isinstance(d, dict) or not d:
            return ("empty_payload", None)
        missing = [k for k in REQUIRED_KEYS if k not in d]
        if missing:
            return ("missing_keys", missing)
        dets = d.get("detections")
        if not isinstance(dets, list):
            return ("detections_not_list", None)
        if len(dets) > MAX_DETS:
            return ("too_many_detections", len(dets))
        for i, det in enumerate(dets):
            if not isinstance(det, dict):
                return ("det_not_object", i)
            if "conf" in det and not _is_finite_number(det["conf"]):
                return ("bad_conf", i)
            if "bbox" in det:
                bb = det["bbox"]
                if (not isinstance(bb, list)) or (len(bb) != 4) or (not all(_is_finite_number(v) for v in bb)):
                    return ("bad_bbox", i)
        try:
            json.dumps(d, allow_nan=False)
        except ValueError:
            return ("non_finite_values", None)
        return None

    @app.route("/api/payload_push", methods=["POST"])
    def payload_push():
        raw = request.get_data(cache=False, as_text=True)
        ctype = request.headers.get("Content-Type", "")

        data = None
        try:
            data = request.get_json(silent=False, force=("application/json" not in ctype))
        except Exception as e:
            _dedup_od1502("invalid_json get_json()", {"ctype": ctype, "raw[:200]": raw[:200], "err": str(e)}, level="debug")

        if data is None:
            try:
                if request.form:
                    data = {k: _coerce_scalar(v) for k, v in request.form.items()}
                    if isinstance(data.get("detections"), str):
                        try:
                            data["detections"] = json.loads(data["detections"])
                        except Exception:
                            pass
            except Exception as e:
                _dedup_od1502("invalid_json form()", {"ctype": ctype, "err": str(e)}, level="debug")

        if data is None:
            data = _try_parse_non_json_body(raw)

        if data is None:
            _dedup_od1502("invalid_json no_parse", {"ctype": ctype, "raw[:200]": raw[:200]}, level="warning")
            return jsonify(ok=False, err="invalid_json"), 400

        body = _server_side_schema_fixups(dict(data))
        err = _validate_od_payload(body)
        if err:
            name, detail = err
            code = 413 if name == "too_many_detections" else 400
            _dedup_od1502(name, {"detail": detail, "keys": list(body.keys()), "ctype": ctype}, level=("error" if code == 413 else "debug"))
            return jsonify(ok=False, err=name, detail=detail), code

        body.setdefault("payload_version", PAYLOAD_VERSION)
        if "objdet" not in body:
            body["objdet"] = _get_empty_objdet_payload()
        with LAST_PAYLOAD_LOCK:
            globals()["LAST_PAYLOAD"] = body

        return jsonify(ok=True, stored=True, ts=time.time()), 200

    # ---- Metrics/Diagnostics ----
    @app.route("/api/metrics", methods=["GET"])
    def api_metrics():
        try:
            src = get_shared_payload()
            if not src:
                with LAST_PAYLOAD_LOCK:
                    src = (LAST_PAYLOAD or {})
            norm = normalize_payload(src if isinstance(src, dict) else {})
            return jsonify(ok=True, **norm), 200
        except Exception as e:
            logger.exception("Error in /api/metrics")
            return jsonify(ok=False, error=str(e)), 500

    @app.route("/api/diagnostics", methods=["GET"])
    def api_diagnostics():
        diag: Dict[str, Any] = {"ok": True, "errors": [], "warnings": []}
        try:
            shared = get_shared_payload()
            local = None
            if not shared:
                with LAST_PAYLOAD_LOCK:
                    local = LAST_PAYLOAD.copy() if isinstance(LAST_PAYLOAD, dict) else None
            payload = shared or local or {}
            diag["payload_ok"] = bool(payload)
            diag["payload_version"] = payload.get("payload_version", PAYLOAD_VERSION)

            opened = running = False
            gs = _import_get_streamer()
            if callable(gs):
                s = gs()
                opened = bool(getattr(s, "is_open", lambda: False)())
                running = bool(getattr(s, "is_running", lambda: False)())
            diag["video"] = {"opened": opened, "running": running}

            with OBJDET_STATUS_LOCK:
                st = dict(OBJDET_STATUS)
            diag["objdet"] = st
            diag["app_version"] = APP_VERSION
            diag["ts"] = time.time()
            return jsonify(diag), 200
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    # ===== Exercise API =====
    @app.route("/api/exercise/settings", methods=["GET"])
    def api_exercise_settings():
        if not _EXR_OK:
            return jsonify(ok=False, error="engine_unavailable"), 503
        try:
            return jsonify(ok=True, settings=json.loads(EXR_SETTINGS.dump())), 200
        except Exception as e:
            logger.exception("exercise_settings failed")
            return jsonify(ok=False, error=str(e)), 500

    @app.post("/api/exercise/simulate")
    def api_exercise_simulate():
        """
        תומך בשני מצבים:
          • default -> schema של sets/reps (לבדיקות/תרשימי חזרות)
          • as="report" או full_report=true -> דו״ח מלא רנדומלי (build_simulated_report)
        פרמטרים שימושיים: mode [good|shallow|missing|mixed], sets, reps, noise, seed
        """
        j = request.get_json(silent=True) or {}
        mode = j.get("mode")
        # דו״ח מלא?
        want_report = (str(j.get("as") or "").lower() in ("report", "full", "full_report")) or bool(j.get("full_report"))
        if want_report and callable(build_simulated_report):
            sets = int(j.get("sets", 1))
            reps = int(j.get("reps", 5))
            noise = float(j.get("noise", 0.12))
            seed = j.get("seed")  # אם None -> רנדומלי בכל קליק
            report = build_simulated_report(mode=mode or "mixed", sets=sets, reps=reps, noise=noise, seed=seed)
            return jsonify(report), 200

        # אחרת — סכימת sets/reps (שומר תאימות)
        if simulate_exercise is None:
            return jsonify(ok=False, error="simulate_unavailable"), 501
        sets = int(j.get("sets", 1))
        reps = int(j.get("reps", 6))
        mean = float(j.get("mean_score", 0.75))
        std  = float(j.get("std", 0.1))
        seed = j.get("seed", 42)
        out = simulate_exercise(sets, reps, mean, std, mode=mode, noise=j.get("noise"), seed=seed)
        return jsonify(out), 200

    @app.post("/api/exercise/score")
    def api_exercise_score():
        if analyze_exercise is None and simulate_exercise is None:
            return jsonify(ok=False, error="exercise_analyzer_unavailable"), 501

        j = request.get_json(silent=True) or {}
        metrics = j.get("metrics")
        if metrics and analyze_exercise:
            result = analyze_exercise({"metrics": metrics, "exercise": j.get("exercise") or {}})
            with LAST_EXERCISE_REPORT_LOCK:
                globals()["LAST_EXERCISE_REPORT"] = result
            return jsonify(result), 200

        payload = None
        try:
            payload = get_shared_payload()
        except Exception:
            pass
        if not payload and isinstance(LAST_PAYLOAD, dict):
            payload = dict(LAST_PAYLOAD)

        if payload and analyze_exercise:
            result = analyze_exercise(payload)
            with LAST_EXERCISE_REPORT_LOCK:
                globals()["LAST_EXERCISE_REPORT"] = result
            return jsonify(result), 200

        if simulate_exercise:
            return jsonify(simulate_exercise()), 200
        return jsonify(ok=False, error="no_metrics_and_no_sim"), 503

    @app.route("/api/exercise/detect", methods=["POST"])
    def api_exercise_detect():
        if not _EXR_OK:
            return jsonify(ok=False, error="engine_unavailable"), 503
        t0 = time.time()
        try:
            body = request.get_json(force=True, silent=False) or {}
        except Exception:
            return jsonify(ok=False, error="bad_json"), 400

        metrics_raw = body.get("metrics") if isinstance(body, dict) else None
        if not isinstance(metrics_raw, dict):
            return jsonify(ok=False, error="missing_metrics_object"), 400

        def _fallback_sanitize(obj: Dict[str, Any]) -> Dict[str, Any]:
            out = {}
            for k, v in obj.items():
                if isinstance(v, (int, float)) and math.isfinite(float(v)):
                    out = {**out, k: float(v)}
                elif isinstance(v, str):
                    t = v.strip()
                    try:
                        if t.lower() in ("true", "false"):
                            out[k] = (t.lower() == "true")
                        else:
                            fv = float(t) if "." in t else float(int(t))
                            if math.isfinite(fv):
                                out[k] = fv
                    except Exception:
                        if k in ("rep.phase", "view.mode", "view.primary"):
                            out[k] = t
                elif isinstance(v, bool):
                    out[k] = v
            return out

        metrics = sanitize_metrics_payload(metrics_raw) if callable(sanitize_metrics_payload) else _fallback_sanitize(metrics_raw)
        exercise_id = body.get("exercise_id")
        if exercise_id is not None and not isinstance(exercise_id, str):
            exercise_id = None

        try:
            lib = _get_engine_library()
        except Exception as e:
            logger.exception("failed to load exercise library")
            return jsonify(ok=False, error=f"library_load_failed: {e}"), 500

        try:
            report = exr_run_once(raw_metrics=metrics, library=lib, exercise_id=exercise_id, payload_version="1.0")
        except Exception as e:
            logger.exception("runtime.run_once failed")
            return jsonify(ok=False, error=f"runtime_failed: {e}"), 500

        sc = report.get("scoring", {}) if isinstance(report, dict) else {}
        if "score_pct" not in sc and isinstance(sc.get("score"), (int, float)):
            try: sc["score_pct"] = int(round(float(sc["score"]) * 100))
            except Exception: pass
        q = sc.get("quality")
        if not sc.get("grade") and isinstance(q, str) and q.strip().upper() in list("ABCDEF"):
            sc["grade"] = q.strip().upper()
        report["scoring"] = sc

        with LAST_EXERCISE_REPORT_LOCK:
            globals()["LAST_EXERCISE_REPORT"] = report

        took_ms = int((time.time() - t0) * 1000.0)
        logger.info(f"[EXR] detect done in {took_ms} ms | ex={report.get('exercise',{}).get('id')} | "
                    f"score={report.get('scoring',{}).get('score_pct')} | "
                    f"unscored={report.get('scoring',{}).get('unscored_reason') or '-'}")
        return jsonify(ok=True, took_ms=took_ms, report=report), 200

    @app.route("/api/exercise/last", methods=["GET"])
    def api_exercise_last():
        with LAST_EXERCISE_REPORT_LOCK:
            rep = LAST_EXERCISE_REPORT.copy() if isinstance(LAST_EXERCISE_REPORT, dict) else None
        return jsonify(ok=bool(rep), report=rep)

    # ---------- Session Status (וידאו/סטרימר) ----------
    @app.get("/api/session/status")
    def api_session_status():
        import time as _t
        fps = 0.0
        size = (0, 0)
        source = "unknown"
        opened = False
        running = False
        try:
            gs = _import_get_streamer()
            if callable(gs):
                s = gs()
                try:  fps = float(getattr(s, "last_fps", lambda: 0.0)() or 0.0)
                except Exception: pass
                try:  size = getattr(s, "last_frame_size", lambda: (0, 0))() or (0, 0)
                except Exception: pass
                try:  source = getattr(s, "source_name", lambda: "camera")() or "camera"
                except Exception: pass
                try:  opened = bool(getattr(s, "is_open", lambda: getattr(s, "opened", False))())
                except Exception: opened = bool(getattr(s, "opened", False))
                try:  running = bool(getattr(s, "is_running", lambda: getattr(s, "running", False))())
                except Exception: running = bool(getattr(s, "running", False))
        except Exception:
            pass
        w, h = (int(size[0]), int(size[1])) if isinstance(size, (tuple, list)) and len(size) >= 2 else (0, 0)
        return jsonify({
            "opened": opened,
            "running": running,
            "fps": float(fps),
            "size": [w, h],
            "source": source,
            "ts": _t.time(),
        }), 200

    # ---------- Exercise Diagnostics Snapshot ----------
    @app.get("/api/exercise/diag")
    def api_exercise_diag_snapshot():
        import time as _t
        snap: Dict[str, Any] = {}
        try:
            snap = get_shared_payload() or {}
        except Exception:
            snap = {}
        if not snap:
            with LAST_PAYLOAD_LOCK:
                if isinstance(LAST_PAYLOAD, dict):
                    snap = dict(LAST_PAYLOAD)

        metrics = snap.get("metrics") or {}
        metrics_keys = []
        try:
            if isinstance(metrics, dict):
                metrics_keys = list(metrics.keys())
            elif isinstance(metrics, list):
                metrics_keys = [m.get("name") for m in metrics if isinstance(m, dict) and "name" in m]
        except Exception:
            metrics_keys = []

        out = {
            "ok": True,
            "ts": _t.time(),
            "view_mode": snap.get("view_mode"),
            "meta": snap.get("meta", {}),
            "metrics_keys": metrics_keys[:50],
        }
        return jsonify(out), 200

    # ---- לוגים כלליים ----
    @app.route("/api/logs", methods=["GET"])
    def api_logs():
        try:
            since = float(request.args.get("since") or request.args.get("since_ts") or 0)
        except ValueError:
            since = 0.0
        level = (request.args.get("level") or "").upper().strip()
        limit = int(request.args.get("max") or request.args.get("limit") or LOGS_API_MAX_ITEMS)
        limit = max(1, min(limit, LOGS_API_MAX_ITEMS))
        buf_list = list(LOG_BUFFER)
        items = [x for x in buf_list if x.get("ts", 0) > since and (not level or x.get("level") == level)]
        if len(items) > limit:
            items = items[-limit:]
        return jsonify(items=items, total=len(buf_list), now=time.time())

    @app.route("/api/logs/clear", methods=["POST"])
    def logs_clear():
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

    @app.route("/api/logs/download", methods=["GET"])
    def logs_download():
        lines = []
        for i in LOG_BUFFER:
            t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(i.get("ts", time.time())))
            lines.append(f"[{t}] [{i.get('level','INFO')}] {i.get('msg','')}")
        payload = "\n".join(lines).encode("utf-8")
        return Response(
            payload,
            mimetype="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="logs.txt"'}
        )

    @app.route("/api/logs/stream", methods=["GET"])
    def logs_stream():
        try:
            init = int(request.args.get("init") or LOG_STREAM_INIT_MAX)
            init = max(0, min(init, LOG_STREAM_INIT_MAX))
        except Exception:
            init = LOG_STREAM_INIT_MAX
        try:
            burst = int(request.args.get("burst") or LOG_STREAM_BURST_MAX)
            burst = max(1, min(burst, LOG_STREAM_BURST_MAX))
        except Exception:
            burst = LOG_STREAM_BURST_MAX
        try:
            ping_ms = int(request.args.get("ping_ms") or LOG_STREAM_PING_MS)
            ping_ms = max(1000, ping_ms)
        except Exception:
            ping_ms = LOG_STREAM_PING_MS

        def gen():
            if LOG_BUFFER:
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
                    if (time.time() - last_ping) * 1000.0 >= ping_ms:
                        yield ":ping\n\n"
                        last_ping = time.time()
                except GeneratorExit:
                    break
                except Exception:
                    pass

        return Response(stream_with_context(gen()), mimetype="text/event-stream")

    # ---- שגיאות ----
    @app.errorhandler(404)
    def not_found(_e):
        msg = {"error": "Not Found",
               "hint": "Check route name and that templates/static paths are correct.",
               "template_dir_exists": TPL_DIR.exists(),
               "static_dir_exists": STATIC_DIR.exists()}
        return jsonify(msg), 404

    @app.errorhandler(Exception)
    def _handle_any_error(e):
        logger.exception("Unhandled exception in request")
        return Response("Server error:\n" + str(e), status=500,
                        mimetype="text/plain; charset=utf-8")

    return app


# =================== Main ===================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app = create_app()
    logger.info("Server ready. /payload ו-/video זמינים. /capture לפתיחת מצלמה בדפדפן לשידור ingest.")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
