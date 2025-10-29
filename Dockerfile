# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro Serverless Proxy (port 8000)
# ------------------------------------------------------------
# גרסה יציבה להרצה בענן (RunPod / App Runner / Docker Desktop)
# כולל התקנת דרישות לפי requirements.txt ו-constraints.txt
# ============================================================

FROM python:3.11-slim

# --- הגדרות סביבת ריצה בסיסיות ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000

# --- התקנת חבילות מערכת קלות (curl/ca/tzdata) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# --- תיקיית עבודה אחידה ---
WORKDIR /app

# --- העתקת דרישות ---
COPY requirements.txt constraints.txt /app/

# --- התקנת ספריות פייתון לפי constraints ---
# שימוש ב-index של PyTorch CPU בלבד
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt -c constraints.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# --- העתקת קוד האפליקציה ---
COPY . /app

# --- חשיפת הפורט של ה-proxy ---
EXPOSE 8000

# --- בדיקת בריאות (Healthcheck) ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/_proxy/health" || exit 1

# --- נקודת הרצה יציבה ---
# מריץ את שרת Flask דרך Gunicorn (admin_web/runpod_proxy.py)
CMD ["gunicorn", "-k", "gthread", "-w", "1", "--threads", "8", "-t", "120", "-b", "0.0.0.0:8000", "admin_web.runpod_proxy:app"]
