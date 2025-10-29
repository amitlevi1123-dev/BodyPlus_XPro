# -*- coding: utf-8 -*-
"""
tools/diag_env.py — בדיקת סביבת עבודה וגרסאות קריטיות
ריצה: python tools/diag_env.py
"""
import os, sys, importlib, json

CHECKS = [
    ("flask", "__version__"),
    ("flask_cors", "__version__"),
    ("werkzeug", "__version__"),
    ("jinja2", "__version__"),
    ("loguru", "__version__"),
    ("coloredlogs", "__version__"),
    ("humanfriendly", "__version__"),
    ("yaml", "__version__"),               # PyYAML
    ("psutil", "__version__"),
    ("requests", "__version__"),
    ("tqdm", "__version__"),
    ("pandas", "__version__"),
    ("numpy", "__version__"),
    ("protobuf", "__version__"),
    ("mediapipe", "__version__"),
    ("onnxruntime", "__version__"),
    ("cv2", "__version__"),
    ("torch", "__version__"),
    ("torchvision", "__version__"),
    ("ultralytics", "__version__"),
    ("scipy", "__version__"),
    ("typing_extensions", "__version__"),
]

def version_of(mod, attr="__version__"):
    try:
        m = importlib.import_module(mod)
        v = getattr(m, attr, None)
        return "UNKNOWN" if v is None else str(v)
    except Exception as e:
        return f"MISSING ({type(e).__name__}: {e})"

def try_extra():
    info = {}
    # Torch: CUDA/CPU
    try:
        import torch
        info["torch_cuda_available"] = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
        info["torch_device_count"] = torch.cuda.device_count() if getattr(torch, "cuda", None) else 0
    except Exception as e:
        info["torch_cuda_available"] = False
        info["torch_device_count"] = 0
        info["torch_note"] = f"torch check failed: {e}"

    # onnxruntime providers
    try:
        import onnxruntime as ort
        info["onnx_providers"] = ort.get_available_providers()
    except Exception as e:
        info["onnx_providers"] = [f"ERROR: {e}"]

    # OpenCV build info (רק snippet)
    try:
        import cv2
        info["cv2_built_with_ffmpeg"] = "FFMPEG" in (cv2.getBuildInformation() or "")
    except Exception as e:
        info["cv2_built_with_ffmpeg"] = f"ERROR: {e}"

    # MediaPipe smoke test (טעינה מהירה של מודול Pose)
    try:
        import mediapipe as mp
        _ = mp.solutions.pose
        info["mediapipe_pose_import"] = "OK"
    except Exception as e:
        info["mediapipe_pose_import"] = f"ERROR: {e}"

    # Ultralytics smoke test (רק יבוא + גרסה)
    try:
        import ultralytics as u
        info["ultralytics_ok"] = True
    except Exception as e:
        info["ultralytics_ok"] = f"ERROR: {e}"

    return info

def main():
    print("=== BodyPlus_XPro • Environment Check ===")
    print("python_exe :", sys.executable)
    print("workdir    :", os.getcwd())
    print("PYTHONPATH :", os.environ.get("PYTHONPATH",""))
    print("-----------------------------------------")
    rows = []
    for mod, attr in CHECKS:
        v = version_of(mod, attr)
        rows.append((mod, v))
        print(f"{mod:18} {v}")

    print("-----------------------------------------")
    extra = try_extra()
    for k, v in extra.items():
        print(f"{k:22} {v}")

    # יצוא JSON אופציונלי (לדוחות)
    out = {
        "python": sys.version,
        "exe": sys.executable,
        "cwd": os.getcwd(),
        "PYTHONPATH": os.environ.get("PYTHONPATH",""),
        "modules": {k:v for k,v in rows},
        "extra": extra,
    }
    os.makedirs("report", exist_ok=True)
    with open("report/env_check.json","w",encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nSaved report -> report/env_check.json")

if __name__ == "__main__":
    main()
