# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro (Admin UI + API)
# ------------------------------------------------------------
# רץ בענן (RunPod/כל דוקר), עם Gunicorn ו-Healthcheck.
# לא מתקין constraints.txt בכלל (כדי למנוע שבירת נתיבי Windows).
# ============================================================

FROM python:3.11-slim

# --- בסיס יציב לסביבה ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    # ברירת מחדל בענן: 8000. מקומית server.py ישתמש ב-5000 אם לא תגדיר PORT.
    PORT=8000 \
    PORT_HEALTH=8000 \
    RUNPOD=1 \
    NO_CAMERA=1

WORKDIR /app

# --- מערכת קלה (curl, tzdata, libgl לתמיכה ב-Image libs) ---
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- דרישות פייתון ---
# חשוב: לא מעתיקים constraints.txt ולא מתקינים ממנו.
COPY requirements.txt /app/
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt
# הערה: אם אתה צריך Torch CPU, אפשר להוסיף:
# && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# --- קוד האפליקציה ---
COPY . /app

# --- פורטים ---
EXPOSE 8000

# --- Healthcheck: קודם /healthz (אם קיים), אחרת /ping ---
HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT_HEALTH:-$PORT}/healthz" \
   || curl -fsS "http://127.0.0.1:${PORT_HEALTH:-$PORT}/ping" || exit 1

# --- הרצה עם Gunicorn (WSGI) ---
# מצביעים על אובייקט WSGI קיים: admin_web.server:app
CMD ["gunicorn",
     "-k", "gthread",
     "-w", "1",
     "--threads", "8",
     "-t", "120",
     "-b", "0.0.0.0:8000",
     "admin_web.server:app"]
