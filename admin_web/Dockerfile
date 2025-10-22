FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app
ENV BODYPLUS_API_HOSTPORT=http://host.docker.internal:5001
ENV REQUEST_TIMEOUT_SEC=2.0
ENV ADMIN_PORT=8000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "server.py", "--host=0.0.0.0", "--port=8000"]
