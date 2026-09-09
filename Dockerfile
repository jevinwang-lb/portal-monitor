FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY domains.txt .

RUN mkdir -p /data

ENV DOMAINS_FILE=/app/domains.txt
ENV STATE_FILE=/data/status.json
ENV PLAYWRIGHT_HEADLESS=true
ENV IGNORE_HTTPS_ERRORS=false

CMD ["python", "/app/app/monitor.py"]