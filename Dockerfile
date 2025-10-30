# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro (RunPod Ready, no constraints.txt)
# ------------------------------------------------------------
# מריץ את ממשק Flask בענן (Gunicorn) בלי מצלמה ובלי tkinter.
# אין שימוש בקובץ constraints.txt בכלל.
# ============================================================

FROM python:3.11-slim

# --- הגדרות סביבת ריצה בסיסיות ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    NO_CAMERA=1 \
    NO_TK=1

# --- תיקיית עבודה אחידה ---
WORKDIR /app

# --- התקנת חבילות מערכת קלות (curl / tzdata / libgl) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- העתקת דרישות בלבד (לא constraints.txt) ---
COPY requirements.txt /app/

# --- התקנת ספריות פייתון ---
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# --- העתקת כל קבצי הפרויקט ---
COPY . /app

# --- חשיפת פורט השרת ---
EXPOSE 8000

# --- בדיקת בריאות אוטומטית ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

# --- פקודת ריצה (Gunicorn) ---
CMD ["bash","-lc","gunicorn -k gthread -w 1 --threads 8 -t 120 --bind 0.0.0.0:${PORT} 'admin_web.server:create_app'"]
