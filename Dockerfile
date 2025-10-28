# -------- Dockerfile (Proxy mode, port 8000) --------
FROM python:3.11-slim

# סביבה בסיסית
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=8 \
    GUNICORN_TIMEOUT=120

# חבילות מערכת נדרשות
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# תיקיית עבודה
WORKDIR /app

# דרישות פייתון
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir flask gunicorn requests

# קוד האפליקציה
COPY . /app

# חשיפת פורט
EXPOSE 8000

# בדיקת בריאות
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/_proxy/health" || exit 1

# ✨ נקודת הרצה: מריץ את הפרוקסי שלך
CMD ["gunicorn", "-b", "0.0.0.0:8000", "admin_web.runpod_proxy:app"]
