# -------- Dockerfile (App mode — works with main.py) --------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5000

# חבילות מערכת
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt || \
    pip install --no-cache-dir flask requests

COPY . /app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || curl -fsS "http://127.0.0.1:${PORT}/ping" || exit 1

# ✨ מריץ ישירות את main.py — הוא כבר מכיל תנאים לסביבת ענן
CMD ["python", "main.py"]
