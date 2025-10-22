# core/system/monitor.py
# =============================================================================
# 🧠 BodyPlus XPro — System Monitor (גרסת EMA + warmup למדידות יציבות)
# =============================================================================
from __future__ import annotations
import os, time, platform, socket
from typing import Any, Dict, Optional

import psutil

# ----------------------- Utilities / globals -----------------------
def _ema(prev: Optional[float], new: Optional[float], alpha: float = 0.3) -> Optional[float]:
    if new is None:
        return prev
    return new if prev is None else (prev * (1 - alpha) + new * alpha)

# חימום ראשוני כדי למנוע 0% בקריאה הראשונה
try:
    _ = psutil.cpu_percent(interval=None)
except Exception:
    pass

_PROC = psutil.Process(os.getpid())
try:
    _ = _PROC.cpu_percent(interval=None)
except Exception:
    pass

# EMA state
_EMA_CPU_TOTAL: Optional[float] = None
_EMA_CPU_PROC: Optional[float]  = None

# קוד קודם שלך
def _is_docker() -> bool:
    try:
        if os.path.exists("/.dockerenv"):
            return True
        cpath = "/proc/1/cgroup"
        if os.path.exists(cpath):
            with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            return "docker" in txt or "kubepods" in txt
    except Exception:
        pass
    return False

def _env_info() -> Dict[str, Any]:
    try:
        boot_time = psutil.boot_time()
    except Exception:
        boot_time = None
    return {
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "os": {"system": platform.system(), "release": platform.release(), "version": platform.version()},
        "python": platform.python_version(),
        "pid": os.getpid(),
        "uptime_sec": (time.time() - boot_time) if boot_time else None,
        "is_docker": _is_docker(),
    }

# ----------------------- GPU (NVML/CUDA אופציונלי) -----------------------
_HAS_NVML = False
try:
    import pynvml  # type: ignore
    try:
        pynvml.nvmlInit()
        _HAS_NVML = True
    except Exception:
        _HAS_NVML = False
except Exception:
    _HAS_NVML = False

def _cuda_available() -> bool:
    try:
        import torch  # type: ignore
        return bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    except Exception:
        return False

def _gpu_info() -> Dict[str, Any]:
    via_cuda = _cuda_available()
    if not _HAS_NVML:
        return {
            "available": False,
            "via_nvml": False,
            "via_cuda": via_cuda,
            "name": None,
            "percent": None,
            "mem_percent": None,
            "temp": None,
        }
    try:
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h).decode("utf-8", errors="ignore")
        util = pynvml.nvmlDeviceGetUtilizationRates(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        memp = (mem.used / mem.total * 100.0) if mem.total else None
        return {
            "available": True,
            "via_nvml": True,
            "via_cuda": via_cuda,
            "name": name,
            "percent": float(util.gpu),
            "mem_percent": float(memp) if memp is not None else None,
            "temp": float(temp) if temp is not None else None,
        }
    except Exception:
        return {
            "available": False,
            "via_nvml": False,
            "via_cuda": via_cuda,
            "name": None,
            "percent": None,
            "mem_percent": None,
            "temp": None,
        }

# ----------------------- תהליך נוכחי (CPU/RSS) -----------------------
def _proc_info() -> Dict[str, Any]:
    global _EMA_CPU_PROC
    try:
        # cpu_percent של תהליך מחזיר 0..(100*num_cpus). ננרמל ל-0..100.
        raw = _PROC.cpu_percent(interval=None)  # אחוז “מוחלט”
        n = max(psutil.cpu_count(logical=True) or 1, 1)
        proc_norm = (raw / float(n))
        _EMA_CPU_PROC = _ema(_EMA_CPU_PROC, proc_norm)
    except Exception:
        proc_norm = None
    try:
        mem = _PROC.memory_info().rss / (1024**3)
        rss_gb = round(mem, 3)
    except Exception:
        rss_gb = None
    return {
        "cpu_percent": round(_EMA_CPU_PROC, 1) if _EMA_CPU_PROC is not None else (round(proc_norm, 1) if proc_norm is not None else None),
        "rss_gb": rss_gb
    }

# ----------------------- rate helpers -----------------------
_prev: Dict[str, Any] = {"t": None, "disk": None, "net": None}

def _rate(prev_val: Optional[int], curr_val: Optional[int], dt: float) -> Optional[float]:
    if prev_val is None or curr_val is None or dt <= 0:
        return None
    try:
        return (float(curr_val) - float(prev_val)) / float(dt)
    except Exception:
        return None

# ----------------------- ספק FPS חיצוני -----------------------
_fps_fn = None
def set_fps_sampler(fn):
    """חברו פונקציה שמחזירה FPS (float). אם לא תחברו — יוחזר None."""
    global _fps_fn
    _fps_fn = fn

# ----------------------- טמפ' CPU (אם קיימת) -----------------------
def _try_cpu_temp() -> Optional[float]:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
        if not temps:
            return None
        for _, entries in temps.items():
            for e in entries:
                cur = getattr(e, "current", None)
                if cur is not None and 0 < float(cur) < 120:
                    return float(cur)
    except Exception:
        return None
    return None

# ----------------------- הסנאפשוט הראשי -----------------------
def get_snapshot() -> Dict[str, Any]:
    """
    החזר dict עם כל המידע הדרוש לדשבורד/טאב מצב מערכת.
    עמיד לשגיאות: אם משהו נכשל — תקבלו None באותו שדה.
    """
    global _prev, _EMA_CPU_TOTAL
    now = time.time()

    # ---- CPU (עם דגימה אמיתית + EMA) ----
    try:
        cpu_total_raw = psutil.cpu_percent(interval=0.3)  # לא interval=None — אחרת 0%
        _EMA_CPU_TOTAL = _ema(_EMA_CPU_TOTAL, cpu_total_raw)
        cpu_total = _EMA_CPU_TOTAL
    except Exception:
        cpu_total_raw = None
        cpu_total = None

    try:
        cpu_per_core_raw = psutil.cpu_percent(interval=None, percpu=True)
    except Exception:
        cpu_per_core_raw = []

    cpu_temp = _try_cpu_temp()

    # ---- RAM ----
    try:
        vm = psutil.virtual_memory()
        ram = {
            "percent": float(vm.percent),
            "used_gb": round(vm.used / (1024 ** 3), 2),
            "total_gb": round(vm.total / (1024 ** 3), 2),
            "available_gb": round(vm.available / (1024 ** 3), 2),
        }
    except Exception:
        ram = {"percent": None, "used_gb": None, "total_gb": None, "available_gb": None}

    # ---- Swap ----
    try:
        sw = psutil.swap_memory()
        swap = {
            "percent": float(sw.percent),
            "used_gb": round(sw.used / (1024 ** 3), 2),
            "total_gb": round(sw.total / (1024 ** 3), 2),
        }
    except Exception:
        swap = {"percent": None, "used_gb": None, "total_gb": None}

    # ---- Disk usage ----
    try:
        du = psutil.disk_usage("/")
        disk_usage = {
            "path": "/",
            "percent": float(du.percent),
            "used_gb": round(du.used / (1024 ** 3), 2),
            "total_gb": round(du.total / (1024 ** 3), 2),
        }
    except Exception:
        disk_usage = {"path": "/", "percent": None, "used_gb": None, "total_gb": None}

    # ---- Disk/Net rates ----
    try:
        dio = psutil.disk_io_counters()
    except Exception:
        dio = None
    try:
        netio = psutil.net_io_counters()
    except Exception:
        netio = None

    dt = (now - _prev["t"]) if _prev["t"] else 0.0
    r_bps = _rate(getattr(_prev["disk"], "read_bytes", None) if _prev["disk"] else None,
                  getattr(dio, "read_bytes", None) if dio else None, dt)
    w_bps = _rate(getattr(_prev["disk"], "write_bytes", None) if _prev["disk"] else None,
                  getattr(dio, "write_bytes", None) if dio else None, dt)
    recv_bps = _rate(getattr(_prev["net"], "bytes_recv", None) if _prev["net"] else None,
                     getattr(netio, "bytes_recv", None) if netio else None, dt)
    sent_bps = _rate(getattr(_prev["net"], "bytes_sent", None) if _prev["net"] else None,
                     getattr(netio, "bytes_sent", None) if netio else None, dt)

    _prev["t"] = now
    _prev["disk"] = dio
    _prev["net"] = netio

    # ---- GPU ----
    gpu = _gpu_info()

    # ---- FPS ----
    fps = None
    try:
        if _fps_fn:
            fps = float(_fps_fn())
    except Exception:
        fps = None

    # ---- Process (התהליך הנוכחי) ----
    proc = _proc_info()

    return {
        "ts": now,
        "env": _env_info(),
        "cpu": {
            # אחוז CPU ממוצע (חלק) — זה מה שתציג בדשבורד
            "percent_total": float(round(cpu_total, 1)) if cpu_total is not None else None,
            # למדידה “גלמית” אם תרצה להשוות
            "percent_total_raw": float(round(cpu_total_raw, 1)) if cpu_total_raw is not None else None,
            "percent_per_core": [float(x) for x in cpu_per_core_raw] if cpu_per_core_raw else [],
            "temp_c": cpu_temp,
        },
        "ram": ram,
        "swap": swap,
        "proc": proc,
        "gpu": gpu,
        "disk": {"usage": disk_usage, "r_bps": r_bps, "w_bps": w_bps},
        "net": {"recv_bps": recv_bps, "sent_bps": sent_bps},
        "fps": fps,
    }
