# -------- Dockerfile (RunPod Serverless Proxy) --------
FROM python:3.11-slim

# סביבה בסיסית
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=8 \
    GUNICORN_TIMEOUT=120

# כלים בסיסיים: curl ל-HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# תלויות פייתון (אם אין requirements.txt, נתקין מינימום)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || \
    pip install --no-cache-dir flask gunicorn requests

# קוד האפליקציה
COPY . /app

# חשיפת הפורט שה-LB של RunPod יגש אליו
EXPOSE 5000

# Healthcheck (בודק /health ואז /ping)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || curl -fsS "http://127.0.0.1:${PORT}/ping" || exit 1

# הרצה: Gunicorn מרים את Flask app מתוך admin_web/runpod_proxy.py
CMD ["bash","-lc","gunicorn -b 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} admin_web.runpod_proxy:app"]
