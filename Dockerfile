# -------- Dockerfile (Proxy-only) --------
FROM python:3.11-slim

# סביבה בסיסית
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=8 \
    GUNICORN_TIMEOUT=120

# חבילות מערכת נדרשות (curl ל-healthcheck, ffmpeg אם תצטרך בעתיד)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# תיקייה לעבודה
WORKDIR /app

# דרישות פייתון (אם יש requirements.txt—העתק והתקן; אחרת נתקין מינימום)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir flask gunicorn requests

# קוד האפליקציה
COPY . /app

# נחשוף את 5000
EXPOSE 5000

# Healthcheck (אם יש לך /health—מצוין; נוסיף גם /ping למקרה ש־RunPod בודק שם)
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || curl -fsS "http://127.0.0.1:${PORT}/ping" || exit 1

# הפקודה שמרימה את הפרוקסי
CMD ["bash","-lc","gunicorn -b 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} admin_web.runpod_proxy:app"]
