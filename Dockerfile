# ------------------------------------------------------------
# Dockerfile — Universal (RunPod + AWS App Runner/ECS)
# Flask + Gunicorn, CPU-based
# ------------------------------------------------------------

FROM python:3.11-slim

# הגדרות סביבתיות בסיסיות + פורט גנרי (מכובד ע"י שני השרתים)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000 \
    GUNICORN_WORKERS=2 \
    GUNICORN_THREADS=8 \
    GUNICORN_TIMEOUT=120

# עבודה כמשתמש לא-רוט (טוב לאבטחה ב-AWS)
# יוצרים יוזר וקבוצה ונעבור אליהם בסוף
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# ספריות מערכת נחוצות (ל-MediaPipe/Onnx/OpenCV-headless אם נדרש)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates tzdata libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# התקנת תלויות פייתון
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# העתקת קוד
COPY . .

# הרצת בריאות: ודא שבאפליקציה יש נתיב /health שמחזיר 200
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# מעבר ליוזר הלא-הרשתי
USER app

# הפעלה עם Gunicorn — מחבר ל-$PORT (App Runner ברירת מחדל 8080, RunPod לרוב 5000)
# אפשר לשלוט בכמות ה-workers/threads דרך משתני סביבה בלי לשנות את התמונה
CMD ["bash", "-lc", "gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS} --threads ${GUNICORN_THREADS} --timeout ${GUNICORN_TIMEOUT} app.main:app"]
