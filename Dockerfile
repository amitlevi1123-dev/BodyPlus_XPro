# ============================================================
# 🧱 Dockerfile — BodyPlus_XPro (RunPod Ready, Unified Ports)
# ============================================================

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONNOUSERSITE=1 \
    PORT=8000 \
    PORT_HEALTH=8000 \
    NO_CAMERA=1 \
    NO_TK=1 \
    RUNPOD=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt \
      --extra-index-url https://download.pytorch.org/whl/cpu

COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT_HEALTH}/healthz" || exit 1

CMD ["bash","-lc","gunicorn -k gthread -w 1 --threads 8 -t 120 --bind 0.0.0.0:${PORT} 'admin_web.server:create_app'"]
