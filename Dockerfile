FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd -r reporter && useradd -r -g reporter -m reporter \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies zuerst (Layer-Cache)
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/
COPY config.example/ ./config.example/
COPY docker-entrypoint.sh ./

RUN mkdir -p /app/config /app/output \
    && cp -r /app/config.example/* /app/config/ \
    && chown -R reporter:reporter /app \
    && chmod +x /app/docker-entrypoint.sh

ENV CONFIG_DIR=/app/config \
    OUTPUT_DIR=/app/output \
    PYTHONPATH=/app

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os, sys; from sqlalchemy import create_engine, text; \
e=create_engine(os.environ.get('DATABASE_URL','sqlite:///:memory:')); \
e.connect().execute(text('SELECT 1')); print('ok')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
