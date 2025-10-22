# core/logs.py
# -------------------------------------------------------
# 🧠 מרכז לוגים ל־BodyPlus XPro — מאוזן: שומר על לוגי-בוט חשובים, חותך ספאם OD
# -------------------------------------------------------

from __future__ import annotations
import os, sys, time, re
from datetime import datetime
from collections import deque, defaultdict
from queue import Queue, Full
from typing import Deque, Dict, Any, Optional, Tuple
from loguru import logger as _logger

# ============================ קונפיג בסיסי ============================

LOG_ROOT = "logs"
APP_NAME = "BodyPlus_XPro"
RETENTION_DAYS = "21 days"
ROTATION_TIME = "00:00"

# ✔ מציג לוגי־בוט חשובים למסך כברירת־מחדל
CONSOLE_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
FILE_LEVEL    = os.getenv("LOG_FILE_LEVEL", "DEBUG").upper()

# ✔ הדשבורד מקבל פחות רעש כברירת־מחדל
UI_LEVEL = os.getenv("LOG_UI_LEVEL", "WARNING").upper()  # DEBUG/INFO/WARNING/ERROR/CRITICAL
LEVEL_ORDER = {"DEBUG":10,"INFO":20,"WARNING":30,"ERROR":40,"CRITICAL":50}
_UI_MIN = LEVEL_ORDER.get(UI_LEVEL, 30)

SUPPRESS_PAYLOAD_PUSH = os.getenv("LOG_SUPPRESS_PAYLOAD_PUSH", "1") not in ("0","false","False")

def _as_bool(name: str, default: str="1") -> bool:
    return os.getenv(name, default) not in ("0","false","False","off","OFF")

RUNTIME_MONITOR_ENABLED = _as_bool("LOG_RUNTIME_MONITOR", "1")
OD_ALERTS_ENABLED       = _as_bool("LOG_OD_ALERTS", "1")
CAM_ALERTS_ENABLED      = _as_bool("LOG_CAM_ALERTS", "1")
SYS_TO_FILE_ONLY        = _as_bool("LOG_SYS_TO_FILE_ONLY", "1")
DEDUP_ENABLED           = _as_bool("LOG_DEDUP_ENABLED", "1")
SAMPLE_ENABLED          = _as_bool("LOG_SAMPLING_ENABLED", "1")

# חלונות דגימה כלליים (לוג רגיל)
try:
    SAMPLING_WINDOW_SEC      = float(os.getenv("LOG_SAMPLING_WINDOW_SEC", "5"))
    SAMPLING_MAX_PER_WINDOW  = int(os.getenv("LOG_SAMPLING_MAX_PER_WINDOW", "8"))
    DEDUP_WINDOW_SEC         = float(os.getenv("LOG_DEDUP_WINDOW_SEC", "1.5"))
except Exception:
    SAMPLING_WINDOW_SEC, SAMPLING_MAX_PER_WINDOW, DEDUP_WINDOW_SEC = 5.0, 8, 1.5

# ============ סינון ייעודי ל־OD + דגימה מחמירה לקודים ״רועשים״ ============

# רמת מינימום להצגת קודי OD “בריאים” (למשל OD1201) במסך/דשבורד
# INFO יראה הכול; WARNING (ברירת־מחדל) יחתוך INFO/DEBUG של “בריא”.
OD_MIN_LEVEL = LEVEL_ORDER.get(os.getenv("LOG_OD_MIN_LEVEL", "WARNING").upper(), 30)

# קודי OD אינפורמטיביים שכיחים (לא שגיאות)
_OD_OK_CODES = {"OD1100","OD1200","OD1201","OD1301","OD1400","OD1501"}

# קודי OD שמציפים לרוב — דוגמים אותם מחמיר (גם אם ברמת ERROR/WARN)
_OD_NOISY_CODES = set((os.getenv("LOG_OD_NOISY_CODES") or "OD1502,OD1402").split(","))

# דגימה מחמירה לקודים רועשים (ברירת־מחדל: אירוע 1 כל 2 שניות לכל קוד+רמה)
NOISY_WINDOW_SEC = float(os.getenv("LOG_OD_NOISY_WINDOW_SEC", "2.0"))
NOISY_MAX_PER_WINDOW = int(os.getenv("LOG_OD_NOISY_MAX_PER_WINDOW", "1"))

# Throttle לאזעקות 🚨 מה־alerts_loop (ברירת־מחדל: אחת כל 8s לכל קוד)
ALERT_MIN_GAP_SEC = float(os.getenv("LOG_ALERT_MIN_GAP_SEC", "8.0"))

def _extract_od_code(msg: str) -> Optional[str]:
    try:
        i = msg.find("[OD")
        if i == -1: return None
        j = msg.find("]", i+1)
        if j == -1: return None
        code = msg[i+1:j]
        return code if code.startswith("OD") else None
    except Exception:
        return None

def _passes_od_filter(level_no: int, msg: str) -> bool:
    code = _extract_od_code(msg or "")
    if not code:
        return True
    # חתוך INFO/DEBUG עבור “בריא”
    if code in _OD_OK_CODES and level_no < OD_MIN_LEVEL:
        return False
    return True

# ======================= זיכרון “חי” לדשבורד + תור SSE =======================

LOG_BUFFER: Deque[Dict[str, Any]] = deque(maxlen=1500)
LOG_QUEUE: Queue = Queue(maxsize=2000)

_last_item: Optional[Tuple[int,str,str]] = None  # (level_no, msg, tag)
_last_item_ts: float = 0.0
_last_item_repeats: int = 0

_sampling_buckets: Dict[Tuple[str,str,Optional[str],int,str], Deque[float]] = defaultdict(lambda: deque())
_noisy_buckets:    Dict[Tuple[str,int], Deque[float]] = defaultdict(lambda: deque())  # (OD_CODE, level_no) -> times
_last_alert_ts:    Dict[str, float] = {}  # per OD/CAM code for 🚨 throttle

def _level_no(name: str) -> int:
    return LEVEL_ORDER.get(name.upper(), 20)

def _record_tag(rec) -> Tuple[str,str,Optional[str]]:
    name = str(rec["name"])
    func = str(rec["function"])
    code = rec["extra"].get("code")
    return (name, func, code if isinstance(code, str) else None)

def _should_sample(rec) -> bool:
    """דגימה כללית + דגימה מחמירה לקודי OD רועשים."""
    if not SAMPLE_ENABLED:
        return True
    try:
        lvl = _level_no(rec["level"].name)
        msg = str(rec["message"])

        # --- דגימה מחמירה לקודים רועשים ---
        od_code = rec["extra"].get("code") or _extract_od_code(msg)
        if od_code and od_code in _OD_NOISY_CODES:
            key = (od_code, lvl)
            now = time.time()
            b = _noisy_buckets[key]
            while b and now - b[0] > NOISY_WINDOW_SEC:
                b.popleft()
            if len(b) >= NOISY_MAX_PER_WINDOW:
                return False
            b.append(now)
            # נמשיך גם דרך הדגימה הכללית (להיות עקביים), אך היא יותר נדיבה

        # --- דגימה כללית ---
        key2 = (*_record_tag(rec), lvl, msg[:120])
        now2 = time.time()
        bucket = _sampling_buckets[key2]
        while bucket and now2 - bucket[0] > SAMPLING_WINDOW_SEC:
            bucket.popleft()
        if len(bucket) >= SAMPLING_MAX_PER_WINDOW:
            return False
        bucket.append(now2)
        return True

    except Exception:
        return True

def _append_ui_item(item: Dict[str, Any]):
    LOG_BUFFER.append(item)
    try:
        LOG_QUEUE.put_nowait(item)
    except Full:
        try:
            for _ in range(50):
                LOG_QUEUE.get_nowait()
        except Exception:
            pass
        try:
            LOG_QUEUE.put_nowait(item)
        except Exception:
            pass

def _memory_sink(message):
    """Sink לדשבורד: סף רמה, סינון OD, דגימה, דה-דופ."""
    global _last_item, _last_item_ts, _last_item_repeats
    try:
        rec = message.record
        lvl_name = str(rec["level"].name).upper()
        lvl_no = _level_no(lvl_name)

        if lvl_no < _UI_MIN:
            return
        if not _passes_od_filter(lvl_no, str(rec["message"])):
            return
        if not _should_sample(rec):
            return
        if SYS_TO_FILE_ONLY and "[SYS]" in str(rec["message"]) and lvl_no < LEVEL_ORDER["WARNING"]:
            return

        ts = float(rec["time"].timestamp())
        msg = str(rec["message"])
        tag = "|".join(x or "" for x in _record_tag(rec))

        if DEDUP_ENABLED and _last_item and lvl_no == _last_item[0] and msg == _last_item[1] and tag == _last_item[2] and (ts - _last_item_ts) <= DEDUP_WINDOW_SEC:
            _last_item_repeats += 1
            try:
                if LOG_BUFFER:
                    LOG_BUFFER[-1]["repeat"] = _last_item_repeats
                return
            except Exception:
                pass

        _append_ui_item({"ts": ts, "level": lvl_name, "msg": msg, "tag": tag})
        _last_item = (lvl_no, msg, tag)
        _last_item_ts = ts
        _last_item_repeats = 0

    except Exception:
        pass

def _console_filter(record):
    """מסך: סינון OD “בריא”, payload_push, ו־[SYS] נמוך."""
    try:
        if not _passes_od_filter(record["level"].no, str(record["message"])):
            return False
        if SUPPRESS_PAYLOAD_PUSH and record["name"] == "admin_web.server" and record["function"] == "payload_push":
            return record["level"].no >= 30
        if SYS_TO_FILE_ONLY and "[SYS]" in str(record["message"]):
            return record["level"].no >= 30
        return True
    except Exception:
        return True

# =========================== אתחול לוגים ===========================

def setup_logging(app_name: str = APP_NAME) -> None:
    _logger.remove()

    session_start = datetime.now()
    day_str  = session_start.strftime("%Y-%m-%d")
    time_str = session_start.strftime("%H-%M-%S")

    day_dir = os.path.join(LOG_ROOT, day_str)
    os.makedirs(day_dir, exist_ok=True)
    file_path = os.path.join(day_dir, f"{time_str}_session_{app_name}.log")

    # למסך
    _logger.add(
        sys.stdout,
        level=CONSOLE_LEVEL,
        colorize=True,
        enqueue=False,
        filter=_console_filter,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "<level>{message}</level>",
    )

    # לקובץ
    _logger.add(
        file_path,
        level=FILE_LEVEL,
        rotation=ROTATION_TIME,
        retention=RETENTION_DAYS,
        enqueue=False,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )

    # לדשבורד/UI
    _logger.add(_memory_sink, level="DEBUG", enqueue=False)

    _logger.info(f"===== {app_name} logging started =====")
    _logger.info(f"Console level={CONSOLE_LEVEL} | File level={FILE_LEVEL} | UI level={UI_LEVEL}")
    _logger.info(f"OD min level={OD_MIN_LEVEL} | Noisy: window={NOISY_WINDOW_SEC}s max={NOISY_MAX_PER_WINDOW} | Alerts gap={ALERT_MIN_GAP_SEC}s")
    _logger.info(f"Sampling: win={SAMPLING_WINDOW_SEC}s max={SAMPLING_MAX_PER_WINDOW} | DeDup={DEDUP_ENABLED}({DEDUP_WINDOW_SEC}s) | SYS->file only={SYS_TO_FILE_ONLY}")

    _install_global_exception_hook()
    if RUNTIME_MONITOR_ENABLED:
        _start_runtime_monitors()

# =========================== לוגר משותף ===========================

logger = _logger
def get_logger(): return logger

# =========================== חריגות גלובליות ===========================

def _install_global_exception_hook():
    def _hook(exc_type, exc_value, exc_tb):
        try:
            import traceback
            tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            _logger.critical(f"🔥 UNHANDLED EXCEPTION ({exc_type.__name__}): {exc_value}")
            _logger.error(tb)
        except Exception:
            pass
    sys.excepthook = _hook

# =========================== מוניטורים (עם Throttle לאזעקות) ===========================

def _start_runtime_monitors(interval_sec: float = 10.0):
    try:
        import threading
        try:
            import psutil
        except Exception:
            psutil = None  # type: ignore

        def _sys_loop():
            if not psutil:
                return
            while True:
                try:
                    cpu = psutil.cpu_percent()
                    mem = psutil.virtual_memory().percent
                    logger.debug(f"[SYS] CPU={cpu:.1f}% | RAM={mem:.1f}%")
                except Exception:
                    pass
                time.sleep(max(1.0, float(interval_sec)))

        def _should_alert(code: str) -> bool:
            now = time.time()
            last = _last_alert_ts.get(code, 0.0)
            if (now - last) >= ALERT_MIN_GAP_SEC:
                _last_alert_ts[code] = now
                return True
            return False

        def _alerts_loop():
            last_seen_ts = -1.0
            od_bad_rx = [
                (re.compile(r"\[(OD15\d{2})]"), "OD payload/build failures"),  # כולל OD1502
                (re.compile(r"\[(OD14\d{2})]"), "OD tracking issues"),        # כולל OD1402
                (re.compile(r"(inference .*error|onnx.*(fail|error)|cuda)", re.I), "OD runtime"),
            ]
            cam_bad_rx = [
                (re.compile(r"\[(CAM1\d{3})]"), "CAM general"),
                (re.compile(r"(cannot open|failed to open|already in use|permission denied)", re.I), "CAM open"),
            ]
            while True:
                try:
                    if LOG_BUFFER:
                        latest = LOG_BUFFER[-1]
                        ts = float(latest.get("ts", 0.0) or 0.0)
                        if ts != last_seen_ts:
                            last_seen_ts = ts
                            msg = str(latest.get("msg", ""))
                            # OD
                            if OD_ALERTS_ENABLED:
                                code = _extract_od_code(msg) or ""
                                if code and code.startswith("OD"):
                                    for rx, tag in od_bad_rx:
                                        m = rx.search(msg)
                                        if m and _should_alert(code):
                                            logger.warning(f"🚨 OD alert ({tag}): {msg}")
                                            break
                            # CAM
                            if CAM_ALERTS_ENABLED:
                                if "[CAM" in msg:
                                    for rx, tag in cam_bad_rx:
                                        m = rx.search(msg)
                                        if m and _should_alert(m.group(1) if m.groups() else "CAM"):
                                            logger.warning(f"🚨 CAM alert ({tag}): {msg}")
                                            break
                except Exception:
                    pass
                time.sleep(0.5)

        threading.Thread(target=_sys_loop,    daemon=True, name="LogSysMon").start()
        threading.Thread(target=_alerts_loop, daemon=True, name="LogAlerts").start()
    except Exception:
        pass

# =========================== OD API ===========================

OD_EVENT_HELP: Dict[str, str] = {
    "OD1000":"Engine start","OD1001":"Model load OK","OD1002":"Model load FAIL",
    "OD1010":"Profile resolved","OD1011":"Profile missing/invalid",
    "OD1020":"Config loaded","OD1021":"Config schema mismatch",
    "OD1100":"Input frame accepted","OD1101":"Empty/None frame","OD1102":"Invalid frame shape/dtype",
    "OD1200":"Inference start","OD1201":"Inference done","OD1202":"Inference FAIL","OD1203":"ONNX/CUDA runtime error",
    "OD1300":"Postprocess start","OD1301":"Postprocess done","OD1302":"Postprocess FAIL","OD1303":"NMS produced 0 boxes",
    "OD1400":"Tracking start","OD1401":"Tracking updated","OD1402":"Tracking lost/FAIL",
    "OD1500":"Payload build start","OD1501":"Payload built","OD1502":"Payload empty/invalid",
    "OD1600":"Provider request","OD1601":"Provider response OK","OD1602":"Provider HTTP/parse FAIL",
    "OD1900":"General","OD1999":"Unhandled exception",
}

def _sanitize_ctx(ctx: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for k, v in ctx.items():
        try:
            if k in ("img","image","frame_data","tensor"):
                safe[k] = f"<{k}:{type(v).__name__} hidden>"
            elif hasattr(v, "shape"):
                safe[k] = f"<{type(v).__name__} shape={getattr(v,'shape','?')}>"
            else:
                safe[k] = v
        except Exception:
            safe[k] = f"<unserializable:{type(v).__name__}>"
    return safe

def od_event(level: str, code: str, msg: str, **ctx):
    try:
        fields = _sanitize_ctx(ctx)
        logger.bind(subsys="OD", code=code, **fields).log(level.upper(), f"[{code}] {msg}")
    except Exception:
        logger.log(level.upper(), f"[{code}] {msg} | ctx={ctx}")

def od_fail(code: str, msg: str, **ctx):
    hint = OD_EVENT_HELP.get(code)
    suffix = f" | hint: {hint}" if hint else ""
    od_event("ERROR", code, f"{msg}{suffix}", **ctx)

class Span:
    def __init__(self, code: str, **ctx):
        from time import perf_counter
        self.code = code
        self.ctx = ctx
        self._t0 = 0.0
        self._ok = False
        self._pf = perf_counter
    def start(self) -> "Span":
        self._t0 = self._pf()
        od_event("DEBUG", self.code, "start", **self.ctx)
        return self
    def ok(self, **extra):
        self._ok = True
        try: self.ctx.update(extra)
        except Exception: pass
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        try: elapsed_ms = round((self._pf() - self._t0) * 1000.0, 2)
        except Exception: elapsed_ms = None
        base = {"elapsed_ms": elapsed_ms} if elapsed_ms is not None else {}
        if exc_type is None:
            lvl = "INFO" if self._ok else "WARNING"
            msg = "done OK" if self._ok else "done (no explicit ok())"
            od_event(lvl, self.code, msg, **base, **self.ctx); return False
        try:
            logger.bind(subsys="OD", code="OD1999", **base, **_sanitize_ctx(self.ctx)).exception("[OD1999] unhandled exception")
        except Exception:
            logger.exception("[OD1999] unhandled exception")
        return False

def od_span(code: str, **ctx) -> Span:
    return Span(code, **ctx).start()

# =========================== CAM API ===========================

CAM_EVENT_HELP: Dict[str, str] = {
    "CAM1000":"Camera start request","CAM1001":"Camera opened OK","CAM1002":"Camera open FAIL",
    "CAM1003":"Camera stop request","CAM1004":"Camera closed","CAM1010":"Switch source/index",
    "CAM1100":"Read frame start","CAM1101":"Read frame OK","CAM1102":"Read frame FAIL/empty","CAM1103":"Invalid frame shape/dtype",
    "CAM1200":"JPEG encode start","CAM1201":"JPEG encode OK","CAM1202":"JPEG encode FAIL","CAM1210":"Downscale applied",
    "CAM1300":"MJPEG client connected","CAM1301":"MJPEG client disconnected","CAM1302":"MJPEG stream error",
    "CAM1400":"FPS update","CAM1999":"Unhandled exception",
}

def cam_event(level: str, code: str, msg: str, **ctx):
    try:
        fields = _sanitize_ctx(ctx)
        logger.bind(subsys="CAM", code=code, **fields).log(level.upper(), f"[{code}] {msg}")
    except Exception:
        logger.log(level.upper(), f"[{code}] {msg} | ctx={ctx}")

def cam_fail(code: str, msg: str, **ctx):
    hint = CAM_EVENT_HELP.get(code)
    suffix = f" | hint: {hint}" if hint else ""
    cam_event("ERROR", code, f"{msg}{suffix}", **ctx)

class CamSpan:
    def __init__(self, code: str, **ctx):
        from time import perf_counter
        self.code = code
        self.ctx = ctx
        self._t0 = 0.0
        self._ok = False
        self._pf = perf_counter
    def start(self) -> "CamSpan":
        self._t0 = self._pf()
        cam_event("DEBUG", self.code, "start", **self.ctx)
        return self
    def ok(self, **extra):
        self._ok = True
        try: self.ctx.update(extra)
        except Exception: pass
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        try: elapsed_ms = round((self._pf() - self._t0) * 1000.0, 2)
        except Exception: elapsed_ms = None
        base = {"elapsed_ms": elapsed_ms} if elapsed_ms is not None else {}
        if exc_type is None:
            lvl = "INFO" if self._ok else "WARNING"
            msg = "done OK" if self._ok else "done (no explicit ok())"
            cam_event(lvl, self.code, msg, **base, **self.ctx); return False
        try:
            logger.bind(subsys="CAM", code="CAM1999", **base, **_sanitize_ctx(self.ctx)).exception("[CAM1999] unhandled exception")
        except Exception:
            logger.exception("[CAM1999] unhandled exception")
        return False

def cam_span(code: str, **ctx) -> CamSpan:
    return CamSpan(code, **ctx).start()
