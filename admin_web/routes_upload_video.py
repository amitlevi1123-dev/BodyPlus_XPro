# -*- coding: utf-8 -*-
"""
routes_upload_video.py — העלאת וידאו + סטרים MJPEG מקובץ (ללא OpenCV)
----------------------------------------------------------------------
• FFmpeg בלבד (subprocess), מתאים לענן.
• "אפמרלי" כברירת מחדל: הקובץ נמחק מיד כשהסטרים מתחיל (בלינוקס), או בסיום (ב-Windows).
• מזרים JPEG-ים בצינור ומגיש אותם כ-/video/stream_file.mjpg.
• במקביל, ת’רד payload_emitter שולח payload "סינתטי" ל-/api/payload_push לבדיקה.

Endpoints:
- GET  /admin/upload-video
- POST /api/upload_video
- GET  /api/upload_video/status
- POST /api/video/use_file           { "fps": 25, "quality": 5 }  (אופציונלי)
- POST /api/video/stop_file
- GET  /video/stream_file.mjpg
- GET  /api/debug/ffmpeg
"""

from __future__ import annotations
import os, time, glob, shutil, threading, subprocess, json, tempfile
from collections import deque
from pathlib import Path
from typing import Dict, Any, Optional, List

from flask import (
    Blueprint, request, jsonify, render_template,
    Response, stream_with_context
)

# ===== Logger =====
try:
    from core.logs import logger  # אם קיימת שכבת לוגים שלך
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("routes_upload_video")

upload_video_bp = Blueprint("upload_video", __name__)

# ============================ Config / Env ============================

SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".mjpg", ".mjpeg", ".webm"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))

# האם למחוק את הקובץ מיד כשהסטרים מתחיל (ללא שמירה)?
EPHEMERAL_UPLOADS = (os.getenv("EPHEMERAL_UPLOADS", "1") == "1")

_LAST_UPLOAD: Dict[str, Any] = {
    "path": None,
    "file_name": None,
    "size": 0,
    "ts": 0.0,
    "last_ok": False,
    "last_err": None,
    "delete_when_done": None,  # מחיקה מאוחרת ב-Windows אם אי אפשר למחוק בזמן שהקובץ פתוח
}

_FILE_STREAM = {
    "proc": None, "lock": threading.Lock(),
    "stderr_tail": deque(maxlen=100), "started_ts": 0.0,
}

_PAY_EMIT = {  # payload-emitter (דימוי מצלמה חיה)
    "thr": None,
    "stop": threading.Event(),
    "fps": 25,
    "last_frame_id": 0,
}

# ============================ FFmpeg Resolver ============================

def _try_run(cmd: List[str]) -> bool:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=4)
        return p.returncode == 0
    except Exception:
        return False

def _verify_ffmpeg(path: str) -> bool:
    return bool(path) and _try_run([path, "-version"])

def _ensure_dir_on_path(bin_path: str) -> None:
    try:
        d = str(Path(bin_path).parent)
        cur = os.environ.get("PATH", "")
        if d not in cur:
            os.environ["PATH"] = d + os.pathsep + cur
    except Exception:
        pass

def _candidates_windows() -> List[str]:
    cands: List[str] = []
    try:
        local = os.environ.get("LOCALAPPDATA") or ""
        patt = str(Path(local) / "Microsoft" / "WinGet" / "Packages"
                   / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
                   / "ffmpeg-*full_build" / "bin" / "ffmpeg.exe")
        cands += glob.glob(patt)
    except Exception:
        pass
    try:
        user = os.environ.get("USERPROFILE") or ""
        cands.append(str(Path(user) / "scoop" / "shims" / "ffmpeg.exe"))
    except Exception:
        pass
    cands += [
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    out, seen = [], set()
    for p in cands:
        if p and p not in seen:
            out.append(p); seen.add(p)
    return out

def resolve_ffmpeg() -> str:
    env_path = os.environ.get("FFMPEG_BIN")
    if env_path and _verify_ffmpeg(env_path):
        _ensure_dir_on_path(env_path)
        return env_path
    w = shutil.which("ffmpeg")
    if w and _verify_ffmpeg(w):
        _ensure_dir_on_path(w)
        return w
    if os.name == "nt":
        for p in _candidates_windows():
            if Path(p).exists() and _verify_ffmpeg(p):
                _ensure_dir_on_path(p); return p
    return "ffmpeg"

def ffmpeg_debug_info() -> Dict[str, Any]:
    path = resolve_ffmpeg()
    info: Dict[str, Any] = {"resolved": path, "ok": False, "head": []}
    try:
        p = subprocess.run([path, "-version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=4)
        txt = (p.stdout or b"").decode("utf-8", errors="replace").splitlines()
        info["code"] = p.returncode; info["ok"] = (p.returncode == 0); info["head"] = txt[:3]
    except Exception as e:
        info["error"] = repr(e)
    return info

FFMPEG_BIN = resolve_ffmpeg()
logger.info(f"[FFMPEG] resolved path: {FFMPEG_BIN!r}")

# ================ Stream mode hook (לשימוש חיצוני אם צריך) ================

def _ffmpeg_proc_running() -> bool:
    with _FILE_STREAM["lock"]:
        p = _FILE_STREAM.get("proc")
        return bool(p and (p.poll() is None))

def get_stream_mode() -> str:
    """ 'file' אם ffmpeg רץ על קובץ; אחרת 'camera'. """
    path = _LAST_UPLOAD.get("path")
    if path and os.path.exists(str(path)) and _ffmpeg_proc_running():
        return "file"
    # אם הקובץ נמחק אפמרלית: עדיין 'file' אם התהליך פעיל
    if _ffmpeg_proc_running():
        return "file"
    return "camera"

# ============================== Helpers ==============================

def _ffmpeg_available() -> bool:
    return _verify_ffmpeg(FFMPEG_BIN)

def _ffmpeg_version() -> Dict[str, Any]:
    try:
        p = subprocess.run([FFMPEG_BIN, "-version"], capture_output=True, text=True, timeout=5)
        return {"ok": (p.returncode == 0), "code": p.returncode, "head": (p.stdout or "").splitlines()[:3]}
    except Exception as e:
        return {"ok": False, "error": repr(e)}

def _stderr_pump(proc: subprocess.Popen):
    try:
        if not proc.stderr:
            return
        for line in iter(proc.stderr.readline, b""):
            try:
                s = line.decode("utf-8", "replace").rstrip()
            except Exception:
                s = str(line).rstrip()
            _FILE_STREAM["stderr_tail"].append(s)
            logger.debug(f"[ffmpeg] {s}")
    except Exception as e:
        logger.debug(f"_stderr_pump exception: {e!r}")

def _stop_ffmpeg():
    with _FILE_STREAM["lock"]:
        p = _FILE_STREAM.get("proc"); _FILE_STREAM["proc"] = None
    try:
        if p and p.poll() is None:
            logger.info("[file_stream] killing ffmpeg process")
            p.kill()
    except Exception as e:
        logger.warning(f"[file_stream] stop error: {e!r}")

def _start_ffmpeg_pipe(path: str, fps: Optional[int] = None, quality: int = 5) -> subprocess.Popen:
    if not Path(path).exists():
        raise FileNotFoundError(f"input_file_missing: {path!r}")
    _stop_ffmpeg()
    vf = f"fps={fps}" if fps else "null"
    args = [
        FFMPEG_BIN, "-hide_banner", "-loglevel", "error",
        "-re", "-i", path, "-an",
        "-vf", vf, "-q:v", str(max(2, min(31, int(quality))))  # 2=איכות גבוהה, 31=נמוכה
        , "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    logger.info(f"[file_stream] starting ffmpeg | bin={FFMPEG_BIN!r} | path={path} | vf={vf} | q={quality}")
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    _FILE_STREAM["stderr_tail"].clear()
    with _FILE_STREAM["lock"]:
        _FILE_STREAM["proc"] = p; _FILE_STREAM["started_ts"] = time.time()
    threading.Thread(target=_stderr_pump, args=(p,), daemon=True).start()

    # --- אפמרלי: נסה למחוק מייד (Linux/Unix תומך unlink-while-open) ---
    try:
        if EPHEMERAL_UPLOADS:
            src = _LAST_UPLOAD.get("path")
            if src and os.path.exists(src):
                if os.name != "nt":
                    Path(src).unlink(missing_ok=True)
                    _LAST_UPLOAD["path"] = None
                else:
                    _LAST_UPLOAD["delete_when_done"] = src
    except Exception as _e:
        logger.debug(f"[upload] ephemeral delete attempt failed: {_e!r}")

    return p

def _mjpeg_from_pipe(p: subprocess.Popen, boundary: str = "frame", chunk_size: int = 4096):
    if not p.stdout:
        logger.error("ffmpeg stdout missing"); return
    buf = bytearray(); soi = b"\xff\xd8"; eoi = b"\xff\xd9"
    try:
        while True:
            if p.poll() is not None:
                logger.warning(f"[file_stream] ffmpeg exited with code={p.returncode}")
                break
            chunk = p.stdout.read(chunk_size)
            if not chunk:
                time.sleep(0.01); continue
            buf.extend(chunk)
            i = buf.find(soi)
            if i > 0: del buf[:i]
            if i == -1: continue
            j = buf.find(eoi, 2)
            if j == -1: continue
            frame = bytes(buf[: j + 2]); del buf[: j + 2]
            yield (
                b"--" + boundary.encode("ascii") + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-store\r\n\r\n" +
                frame + b"\r\n"
            )
    finally:
        _stop_ffmpeg()
        # מחיקה מאוחרת (Windows) + ניקוי מצביע
        try:
            pending = _LAST_UPLOAD.get("delete_when_done")
            if pending and os.path.exists(pending):
                Path(pending).unlink(missing_ok=True)
            _LAST_UPLOAD["delete_when_done"] = None
            _LAST_UPLOAD["path"] = None
        except Exception as _e:
            logger.debug(f"[upload] deferred delete failed: {_e!r}")

def _cleanup_last_upload():
    try:
        p = _LAST_UPLOAD.get("path")
        if p and Path(p).exists():
            Path(p).unlink(missing_ok=True)
    except Exception as e:
        logger.debug(f"[upload] cleanup previous failed: {e!r}")

def _save_upload(file_storage) -> Dict[str, Any]:
    """
    לא שומר קבוע — כותב לקובץ זמני בלבד (יימחק מייד כשיתחיל סטרים, או בסיום/עצירה).
    """
    name = file_storage.filename or "video.bin"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        return {"ok": False, "error": f"extension_not_allowed: {ext}"}

    size = 0
    try:
        tmp = tempfile.NamedTemporaryFile(prefix="upload_", suffix=ext, delete=False)
        tmp_path = tmp.name
        with tmp:
            for chunk in file_storage.stream:
                if not chunk: continue
                size += len(chunk)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    raise RuntimeError("file_too_large")
                tmp.write(chunk)
    except RuntimeError as e:
        try:
            if 'tmp_path' in locals():
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    except Exception as e:
        try:
            if 'tmp_path' in locals():
                Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": False, "error": f"save_failed:{e!r}"}

    _cleanup_last_upload()
    _LAST_UPLOAD.update({
        "path": str(tmp_path),
        "file_name": name,
        "size": size,
        "ts": time.time(),
        "last_ok": True,
        "last_err": None,
        "delete_when_done": None,
    })
    logger.info(f"[upload] saved (temp) | {name} | {size} bytes | {tmp_path}")
    return {"ok": True, "path": str(tmp_path), "file_name": name, "size": size}

# =========================== Payload Emitter ===========================

def _post_payload(payload: Dict[str, Any]) -> bool:
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            SERVER_BASE_URL + "/api/payload_push",
            data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception as e:
        logger.debug(f"[payload_emitter] post failed: {e!r}")
        return False

def _synthetic_measurements(t: float) -> Dict[str, float]:
    import math
    return {
        "shoulder_left_deg":  round(25 + 15*math.sin(t*0.9), 1),
        "shoulder_right_deg": round(28 + 12*math.cos(t*1.1), 1),
        "elbow_left_deg":     round(45 + 20*math.sin(t*1.3+0.7), 1),
        "elbow_right_deg":    round(42 + 22*math.cos(t*1.2+0.3), 1),
        "knee_left_deg":      round(50 + 18*math.sin(t*0.8+1.2), 1),
        "knee_right_deg":     round(49 + 16*math.cos(t*0.85+0.5), 1),
        "torso_tilt_deg":     round(10 +  8*math.sin(t*0.6+0.9), 1),
    }

def _emit_payload_loop():
    fps = max(1, int(_PAY_EMIT["fps"] or 25))
    dt = 1.0 / fps
    logger.info(f"[payload_emitter] start | fps={fps} | post={SERVER_BASE_URL}/api/payload_push")
    t0 = time.time()
    while not _PAY_EMIT["stop"].is_set():
        with _FILE_STREAM["lock"]:
            p = _FILE_STREAM.get("proc")
            running = bool(p and (p.poll() is None))
        if not running:
            break

        _PAY_EMIT["last_frame_id"] += 1
        now = time.time(); t = now - t0
        meas = _synthetic_measurements(t)

        payload = {
            "frame": {"w": 1280, "h": 720, "mirrored": False, "ts_ms": int(now*1000)},
            "frame_id": _PAY_EMIT["last_frame_id"],
            "mp": {"landmarks": [], "mirror_x": False},
            "metrics": dict(meas),
            "detections": [],
            "payload_version": "1.2.0",
            "ts": now,
        }

        _post_payload(payload)
        time.sleep(dt)
    logger.info("[payload_emitter] stop")

def _start_payload_emitter(fps: Optional[int]):
    try:
        _PAY_EMIT["stop"].set()
        thr = _PAY_EMIT.get("thr")
        if thr and thr.is_alive():
            try: thr.join(timeout=0.2)
            except Exception: pass
        _PAY_EMIT["stop"] = threading.Event()
        _PAY_EMIT["fps"] = int(fps) if fps else 25
        _PAY_EMIT["last_frame_id"] = 0
        thr = threading.Thread(target=_emit_payload_loop, daemon=True)
        _PAY_EMIT["thr"] = thr
        thr.start()
    except Exception as e:
        logger.warning(f"[payload_emitter] start failed: {e!r}")

def _stop_payload_emitter():
    try:
        _PAY_EMIT["stop"].set()
    except Exception:
        pass

# ================================ Pages ================================

@upload_video_bp.route("/admin/upload-video", methods=["GET"])
def upload_video_page():
    return render_template(
        "upload_video.html",
        active_page="upload_video_page",
        app_version=os.getenv("APP_VERSION", "dev"),
        allowed=sorted(ALLOWED_EXT),
        max_mb=MAX_UPLOAD_MB,
    )

# ================================= API =================================

@upload_video_bp.route("/api/upload_video", methods=["POST"])
def api_upload_video():
    f = request.files.get("file")
    if not f:
        return jsonify(ok=False, error="missing_file"), 400
    res = _save_upload(f)
    if not res.get("ok"):
        logger.warning(f"[upload] failed: {res}")
        return jsonify(ok=False, **{k: v for k, v in res.items() if k != "ok"}), 400
    return jsonify(
        ok=True,
        file_name=res["file_name"],
        size_bytes=res["size"],
        size_mb=round(res["size"] / (1024 * 1024), 2),
        path=res["path"],      # נתיב זמני בלבד
        persisted=False        # חיווי: לא נשמר קבוע
    ), 200

@upload_video_bp.route("/api/upload_video/status", methods=["GET"])
def api_upload_status():
    d = dict(_LAST_UPLOAD); d["ok"] = True
    with _FILE_STREAM["lock"]:
        p = _FILE_STREAM.get("proc")
        running = bool(p and (p.poll() is None))
        pid = (p.pid if running else None) if p else None
    d.update({
        "file_stream_running": running, "file_stream_pid": pid,
        "ffmpeg": _ffmpeg_version(), "stderr_tail": list(_FILE_STREAM["stderr_tail"]),
        "ffmpeg_resolved": FFMPEG_BIN,
        "payload_emitter": {
            "fps": _PAY_EMIT["fps"],
            "running": bool(_PAY_EMIT.get("thr") and _PAY_EMIT["thr"].is_alive()),
            "last_frame_id": _PAY_EMIT["last_frame_id"],
        },
        "persisted": False,
        "storage": "tmpfs",   # אינדיקציה שזמני
        "ephemeral": EPHEMERAL_UPLOADS,
    })
    return jsonify(d)

@upload_video_bp.route("/api/video/use_file", methods=["POST"])
def api_video_use_file():
    """
    התחלת סטרים דרך FFmpeg + התחלת payload emitter.
    גוף JSON אופציונלי: { "fps": 25, "quality": 5 }
    """
    if not _LAST_UPLOAD["path"]:
        return jsonify(ok=False, error="no_file_uploaded"), 400
    if not _ffmpeg_available():
        return jsonify(ok=False, error="ffmpeg_not_found", resolved=FFMPEG_BIN), 500

    j = request.get_json(silent=True) or {}
    fps_val = j.get("fps")
    fps = int(fps_val) if isinstance(fps_val, (int, float)) or (isinstance(fps_val, str) and str(fps_val).isdigit()) else None
    quality = int(j.get("quality", 5))

    try:
        p = _start_ffmpeg_pipe(_LAST_UPLOAD["path"], fps=fps, quality=quality)
        logger.info(f"[file_stream] started | pid={p.pid} | fps={fps} | q={quality}")
        _start_payload_emitter(fps or 25)
        return jsonify(ok=True, message="file_stream_started",
                       file_name=_LAST_UPLOAD["file_name"], url="/video/stream_file.mjpg",
                       resolved_ffmpeg=FFMPEG_BIN,
                       ephemeral=EPHEMERAL_UPLOADS), 200
    except FileNotFoundError as e:
        logger.error(f"[file_stream] start error: {e!r}")
        return jsonify(ok=False, error="input_file_missing", detail=str(e)), 400
    except Exception as e:
        logger.exception("[file_stream] start exception")
        return jsonify(ok=False, error="ffmpeg_spawn_failed", detail=repr(e),
                       resolved_ffmpeg=FFMPEG_BIN,
                       stderr_tail=list(_FILE_STREAM["stderr_tail"])), 500

@upload_video_bp.route("/api/video/stop_file", methods=["POST"])
def api_video_stop_file():
    _stop_payload_emitter()
    _stop_ffmpeg()
    _cleanup_last_upload()
    _LAST_UPLOAD.update({
        "path": None, "file_name": None, "size": 0,
        "last_ok": False, "delete_when_done": None
    })
    return jsonify(ok=True, stopped=True, cleaned_temp=True)

@upload_video_bp.route("/video/stream_file.mjpg", methods=["GET"])
def video_stream_file_mjpg():
    # גם אם הקובץ כבר נמחק (אפמרלי), אם ffmpeg כבר רץ — נמשיך להזרים
    with _FILE_STREAM["lock"]:
        p = _FILE_STREAM.get("proc")
    if (not p) or (p.poll() is not None):
        # אם אין תהליך רץ — ננסה להפעיל מחדש (רק אם יש path זמני קיים)
        tmp_path = _LAST_UPLOAD.get("path")
        if not tmp_path:
            return Response('{"ok":false,"error":"no_stream_running_or_ephemeral_path_gone"}\n',
                            status=503, mimetype="application/json")
        if not _ffmpeg_available():
            return Response(f'{{"ok":false,"error":"ffmpeg_not_found","resolved":{FFMPEG_BIN!r}}}\n',
                            status=500, mimetype="application/json")
        try:
            p = _start_ffmpeg_pipe(tmp_path)
            _start_payload_emitter(_PAY_EMIT["fps"] or 25)
        except Exception as e:
            logger.exception("[file_stream] autostart failed")
            return Response(f'{{"ok":false,"error":"ffmpeg_autostart_failed","detail":{json.dumps(str(e))}}}\n',
                            status=500, mimetype="application/json")

    boundary = "frame"
    gen = _mjpeg_from_pipe(p, boundary=boundary)
    resp = Response(stream_with_context(gen), mimetype=f"multipart/x-mixed-replace; boundary={boundary}")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

@upload_video_bp.route("/api/debug/ffmpeg", methods=["GET"])
def api_debug_ffmpeg():
    with _FILE_STREAM["lock"]:
        p = _FILE_STREAM.get("proc")
        running = bool(p and (p.poll() is None))
        pid = (p.pid if running else None) if p else None
    dbg = ffmpeg_debug_info()
    return jsonify({
        "available": _ffmpeg_available(),
        "version": dbg,
        "resolved": FFMPEG_BIN,
        "file_stream": {
            "running": running, "pid": pid,
            "started_ts": _FILE_STREAM["started_ts"],
            "stderr_tail": list(_FILE_STREAM["stderr_tail"]),
        },
        "payload_emitter": {
            "fps": _PAY_EMIT["fps"],
            "running": bool(_PAY_EMIT.get("thr") and _PAY_EMIT["thr"].is_alive()),
            "last_frame_id": _PAY_EMIT["last_frame_id"],
        },
        "last_upload": dict(_LAST_UPLOAD),
        "server_base": SERVER_BASE_URL,
        "persisted": False,
        "storage": "tmpfs",
        "ephemeral": EPHEMERAL_UPLOADS,
    })
