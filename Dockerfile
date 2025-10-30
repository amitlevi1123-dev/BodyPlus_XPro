# ============================================================
# 🚀 BodyPlus_XPro — Full Cloud System (Flask + API + Proxy)
# ------------------------------------------------------------
# גרסה אחת שעובדת בענן (RunPod או מקומית)
# מריצה את ה-Flask Admin UI + כל ה-API + RunPod Proxy
# ============================================================

FROM python:3.11-slim

# --- הגדרות סביבה ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    NO_CAMERA=1 \
    RUNPOD=1 \
    PROXY_DEBUG=1

WORKDIR /app

# --- התקנת חבילות מערכת ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- התקנת תלויות פייתון ---
COPY requirements.txt constraints.txt /app/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt -c constraints.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# --- העתקת קוד האפליקציה ---
COPY . /app

EXPOSE 8000

# --- הפעלת הכל ---
CMD ["python", "admin_web/runpod_proxy.py"]
