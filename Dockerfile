# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro (Admin UI + API)
# להרצה בענן (RunPod / App Runner / Docker Desktop)
# מריץ את Flask דרך Gunicorn, עם Healthcheck מובנה.
# ============================================================

FROM python:3.11-slim

# --- בסיס יציב לסביבה ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    RUNPOD=1 \
    NO_CAMERA=1 \
    NO_TK=1

WORKDIR /app

# --- מערכת קלה (curl, tzdata, libgl ל-PIL/MP) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- דרישות פייתון (בלי constraints.txt) ---
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# --- העתקת כל הקוד ---
COPY . /app

# --- פורט השרת ---
EXPOSE 8000

# --- בדיקת בריאות (Healthcheck) ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || curl -fsS "http://127.0.0.1:${PORT}/ping" || exit 1

# --- הרצה עם Gunicorn (threaded) ---
# חשוב: מצביעים על אובייקט app ולא על פונקציה create_app (לא factory).
CMD ["gunicorn",
     "-k","gthread",
     "-w","1","--threads","8",
     "--timeout","120",
     "--bind","0.0.0.0:8000",
     "admin_web.server:app"]
