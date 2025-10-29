# -------- Dockerfile (Serverless Proxy, port 8000) --------
FROM python:3.11-slim

# סביבה בסיסית
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

# חבילות מערכת קלות (לבריאות/בדיקות)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה אחידה בתוך הקונטיינר
WORKDIR /app

# דרישות פייתון (ננסה requirements.txt ואם אין – בסיס)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir flask gunicorn requests

# קוד האפליקציה (כולל admin_web/runpod_proxy.py)
COPY . /app

# פורט הפרוקסי
EXPOSE 8000

# בדיקת בריאות פשוטה לפרוקסי
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/_proxy/health" || exit 1

# ✨ נקודת הרצה יציבה (ללא shell expansion)
# מריץ את הפרוקסי של RunPod Serverless: admin_web/runpod_proxy.py → app
CMD ["gunicorn", "-b", "0.0.0.0:8000", "admin_web.runpod_proxy:app"]
