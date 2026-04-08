FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY telegram-ingestion/requirements.txt /tmp/ingest-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/backend-requirements.txt \
    -r /tmp/ingest-requirements.txt

COPY backend /app/backend
COPY telegram-ingestion /app/ingest

ENV PYTHONPATH=/app/backend
WORKDIR /app/ingest

CMD ["python", "-m", "telegram_ingestion"]
