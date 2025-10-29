# -------- Dockerfile (Proxy mode, port 8000) --------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir flask gunicorn requests

COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:8000/_proxy/health" || exit 1

# חשוב: ב-exec form אין הרחבת ENV, לכן מקבעים 8000 כאן.
CMD ["gunicorn", "-b", "0.0.0.0:8000", "admin_web.runpod_proxy:app"]
