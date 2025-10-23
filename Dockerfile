@'
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 `
    PYTHONUNBUFFERED=1 `
    PIP_NO_CACHE_DIR=1 `
    PORT=5000

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends `
    build-essential libgl1 libglib2.0-0 `
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

CMD ["bash", "-lc", "gunicorn --bind 0.0.0.0:${PORT} app.main:app"]
'@ | Set-Content -Encoding UTF8 Dockerfile
