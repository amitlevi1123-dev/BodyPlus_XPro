# ============================================================
# 🧱 Dockerfile.main — BodyPlus_XPro Full System (Flask Admin UI)
# ------------------------------------------------------------
# גרסה להרצת מערכת הניהול המלאה (app/main.py) בענן או מקומית
# ============================================================

FROM python:3.11-slim

# --- הגדרות בסיס ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    NO_CAMERA=1

WORKDIR /app

# --- התקנת תלויות ---
COPY requirements.txt constraints.txt /app/
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt -c constraints.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

# --- העתקת כל הקוד ---
COPY . /app

EXPOSE 8000

# --- הרצת המערכת הראשית ---
CMD ["python", "app/main.py"]
