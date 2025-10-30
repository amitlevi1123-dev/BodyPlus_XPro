# -*- coding: utf-8 -*-
"""
server.py — Admin UI + API (Browser-only video ingest)
------------------------------------------------------
• Flask (דשבורד, וידאו, לוגים כ-Blueprint) — /video/stream.mjpg
• /payload ו-/api/payload_last
• סטרים MJPEG דרך admin_web.routes_video (ingest מהדפדפן)
• Upload-Video (FFmpeg) נשאר אופציונלי
"""

from __future__ import annotations
import os, json, math, time, threading, logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from flask import (
    Flask, Response, jsonify, render_template, request, send_from_directory,
    redirect, url_for, send_file, make_response
)
from werkzeug.middleware.proxy_fix import ProxyFix

# ===== Blueprints =====
from admin_web.routes_video import video_bp  # ingest + stream

# Upload video (optional)
try:
    from admin_web.routes_upload_video import upload_video_bp
except Exception:
    upload_video_bp = None  # type: ignore

# Actions / State (optional)
try:
    from admin_web.routes_actions import actions_bp, state_bp
except Exception:
    actions_bp = None  # type: ignore
    state_bp = None  # type: ignore

# Logs (optional)
try:
    from admin_web.routes_logs import bp_logs
except Exception:
    bp_logs = None  # type: ignore

# Exercise API (optional)
try:
    from admin_web.routes_exercise import bp_exercise
except Exception:
    bp_exercise = None  # type: ignore

# System/health/diagnostics (אם קיים הוא יחשוף /healthz כבר)
try:
    from admin_web.routes_system import bp_system
except Exception:
    bp_system = None  # type: ignore

# ===== Logging =====
try:
    from core.logs import setup_logging, logger
except Exception:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("server")

# ===== Payload גרסה =====
try:
    from core.payload import PAYLOAD_VERSION
except Exception:
    PAYLOAD_VERSION = "1.2.0"

# ===== payload משותף =====
try:
    from admin_web.state import get_payload as get_shared_payload  # type: ignore
except Exception:
    def get_shared_payload() -> Dict[str, Any]:
        return {}

# ===== Persist (DB) — אתחול בלבד =====
try:
    from db.persist import AVAILABLE as DB_PERSIST_AVAILABLE, init as db_persist_init
except Exception as _e:
    DB_PERSIST_AVAILABLE = False
    def db_persist_init(*args, **kwargs):  # type: ignore
        logger.info(f"[persist] not available ({_e})")

# ===== Config =====
APP_VERSION = os.getenv("APP_VERSION", "dev")
GIT_COMMIT  = os.getenv("GIT_COMMIT", "")[:12] or None
DEFAULT_BACKEND = os.getenv("DEFAULT_BACKEND", "").strip()

ENABLE_HEARTBEAT = os.getenv("ENABLE_HEARTBEAT", "1") == "1"
HEARTBEAT_INTERVAL_SEC = float(os.getenv("HEARTBEAT_INTERVAL_SEC", "30"))

BASE_DIR      = Path(__file__).resolve().parent
TPL_DIR       = BASE_DIR / "templates"
STATIC_DIR    = BASE_DIR / "static"
LEGACY_IMAGES = BASE_DIR / "images"

_NOW_MS = lambda: int(time.time() * 1000)

LAST_PAYLOAD_LOCK = threading.Lock()
LAST_PAYLOAD: Optional[Dict[str, Any]] = None

START_TS = time.time()

# ===== Internals / Utils =====
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
        "frame": {"w": 1280, "h": 720, "mirrored": False, "ts_ms": _NOW_MS()},
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
        from urllib.parse import parse_qs
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
                    if all(isinstance(v,(int,float)) for v in (x,y,w,h)):
                        bb = [float(x), float(y), float(x + w), float(y + h)]
                    else:
                        x1 = bbox.get("x1"); y1 = bbox.get("y1"); x2 = bbox.get("x2"); y2 = bbox.get("y2")
                        if all(isinstance(v,(int,float)) for v in (x1,y1,x2,y2)):
                            bb = [float(x1), float(y1), float(x2), float(y2)]
                elif isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    x1, y1, a, b = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
                    bb = [x1, y1, x1 + a, y1 + b] if a > 0 and b > 0 else [x1, y1, a, b]
            except Exception:
                bb = None
            item: Dict[str, Any] = {}
            if isinstance(conf, (int, float)) and math.isfinite(float(conf)):
                item["conf"] = float(conf)
            if isinstance(bb, list) and len(bb) == 4 and all(isinstance(v,(int,float)) for v in bb):
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

# ===== App factory =====
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

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    if ENABLE_HEARTBEAT:
        threading.Thread(target=_background_log_heartbeat, daemon=True).start()

    # ----- Register blueprints -----
    app.register_blueprint(video_bp)
    if upload_video_bp is not None:
        app.register_blueprint(upload_video_bp)
    if actions_bp is not None:
        app.register_blueprint(actions_bp)
    if state_bp is not None:
        app.register_blueprint(state_bp)
    if bp_logs is not None:
        app.register_blueprint(bp_logs)
    if bp_exercise is not None:
        app.register_blueprint(bp_exercise)
    if bp_system is not None:
        app.register_blueprint(bp_system)

    # ----- Fallback health endpoints (אם bp_system לא סיפק) -----
    if "system._healthz" not in app.view_functions:
        @app.get("/healthz")
        def _healthz():
            return "ok", 200
    if "system._health" not in app.view_functions:
        @app.get("/health")
        def _health():
            return "ok", 200
    if "system._ping" not in app.view_functions:
        @app.get("/ping")
        def _ping():
            return "pong", 200

    # אתחול Persist (DB) — no-op אם לא זמין
    try:
        db_persist_init(default_user_name=os.getenv("DEFAULT_USER_NAME", "Amit"))
        logger.info("DB persist layer: %s", "ON" if DB_PERSIST_AVAILABLE else "OFF")
    except Exception as _e:
        logger.warning(f"DB persist init failed: {_e}")

    logger.info("=== Admin UI (Flask – Browser ingest) ===")
    logger.info(f"APP_VERSION={APP_VERSION}  DEFAULT_BACKEND={DEFAULT_BACKEND or '(none)'}")

    # ----- Global headers / CORS / cache bust -----
    @app.after_request
    def _no_cache(resp: Response):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Accel-Buffering"] = "no"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Ingest-Token"
        return resp

    # ----- Jinja helpers -----
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

    # ----- Static/SPAs -----
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
        if not p.exists() and not filename.endswith(".gz"):
            gz = STATIC_DIR / (filename + ".gz")
            if gz.exists():
                mime = "application/octet-stream"
                if filename.endswith(".js"): mime = "application/javascript"
                elif filename.endswith(".css"): mime = "text/css"
                elif filename.endswith(".html"): mime = "text/html"
                resp = make_response(send_file(gz, mimetype=mime))
                resp.headers["Content-Encoding"] = "gzip"
                return resp
        return send_from_directory(str(STATIC_DIR), filename)

    # ----- Templates -----
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
        return render_template("exercise.html", active_page="exercise_page",
                               page_title="זיהוי תרגיל", app_version=APP_VERSION)

    @app.route("/system", methods=["GET"])
    def system_page():
        return render_template("system.html", active_page="system_page", app_version=APP_VERSION)

    # ---- דף פתיחת מצלמה ----
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

    # ----- Payload APIs -----
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

    @app.route("/api/payload_last", methods=["GET"])
    def api_payload_last():
        try:
            shared = get_shared_payload()
            out = dict(shared) if isinstance(shared, dict) else {}
            if not out:
                with LAST_PAYLOAD_LOCK:
                    out = dict(LAST_PAYLOAD) if isinstance(LAST_PAYLOAD, dict) else {}
            if not out:
                return jsonify({"ok": False, "error": "no_payload"}), 200
            out.setdefault("payload_version", PAYLOAD_VERSION)
            return jsonify(out), 200
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # ----- OD ingest -----
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
            logger.debug("invalid_json get_json(): %s", e)

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
                logger.debug("invalid_json form(): %s", e)

        if data is None:
            data = _try_parse_non_json_body(raw)

        if data is None:
            return jsonify(ok=False, err="invalid_json"), 400

        body = _server_side_schema_fixups(dict(data))
        err = _validate_od_payload(body)
        if err:
            name, detail = err
            code = 413 if name == "too_many_detections" else 400
            return jsonify(ok=False, err=name, detail=detail), code

        body.setdefault("payload_version", PAYLOAD_VERSION)
        if "objdet" not in body:
            body["objdet"] = _get_empty_objdet_payload()
        with LAST_PAYLOAD_LOCK:
            globals()["LAST_PAYLOAD"] = body

        return jsonify(ok=True, stored=True, ts=time.time()), 200

    # ----- Metrics -----
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

    # ----- Error handlers -----
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

    # ----- MJPEG quick test -----
    @app.get("/test_stream")
    def test_stream():
        return Response("""<!doctype html><meta charset="utf-8">
        <title>MJPEG test</title>
        <style>body{margin:0;background:#000;display:grid;place-items:center;height:100vh}</style>
        <img src="/video/stream.mjpg?hud=1" style="max-width:100%;max-height:100vh;object-fit:contain">
        """, mimetype="text/html")

    return app


# === WSGI export (ל-Gunicorn) ===
app = create_app()

# ================================================================
# ריצה מקומית בלבד (לא בענן / RunPod)
# ================================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"[Local] Flask server running at http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False, threaded=True)
