 FROM python:3.11-slim
@@
 ENV PYTHONDONTWRITEBYTECODE=1 \
     PYTHONUNBUFFERED=1 \
     PIP_NO_CACHE_DIR=1 \
     PORT=5000 \
     GUNICORN_WORKERS=2 \
     GUNICORN_THREADS=8 \
     GUNICORN_TIMEOUT=120
+    # --- תצורת וידאו/קבצים (לסטרים מקובץ עם FFmpeg) ---
+    FFMPEG_BIN=/usr/bin/ffmpeg \
+    EPHEMERAL_UPLOADS=1 \
+    SERVER_BASE_URL=http://127.0.0.1:5000 \
+    MAX_UPLOAD_MB=500

@@
-RUN apt-get update && apt-get install -y --no-install-recommends \
-    build-essential curl ca-certificates tzdata libgl1 libglib2.0-0 \
+RUN apt-get update && apt-get install -y --no-install-recommends \
+    build-essential curl ca-certificates tzdata libgl1 libglib2.0-0 ffmpeg \
  && rm -rf /var/lib/apt/lists/*
@@
-HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
+# אם ה-health אצלך ב-/healthz השאר/שנה בהתאם
+HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1
@@
-CMD ["bash", "-lc", "gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} app.main:app"]
+CMD ["bash", "-lc", "gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} app.main:app"]
