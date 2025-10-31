# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro (run main.py directly)
# ------------------------------------------------------------
# קל, יציב, עובד ב-RunPod/כל Docker. לא נוגע ב-constraints.txt.
# ============================================================

FROM python:3.11-slim

# --- סביבה בסיסית ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    RUNPOD=1 \
    NO_CAMERA=1

WORKDIR /app

# --- חבילות מערכת דקות (כולל libgl בשביל חלק מהספריות) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- דרישות פייתון ---
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# אם תרצה Torch CPU:
# RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# --- קוד האפליקציה ---
COPY . /app

# --- פורט ---
EXPOSE 8000

# --- Healthcheck: קודם /healthz ואז /ping של ה-main ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || curl -fsS "http://127.0.0.1:${PORT}/ping" || exit 1

# --- הפעלה: מריץ את ה-main (בלי Gunicorn) ---
CMD ["python", "app/main.py"]

