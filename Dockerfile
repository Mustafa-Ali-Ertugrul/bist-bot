# syntax=docker/dockerfile:1.7

# ---- builder: install deps into a venv via uv ----
FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv_bin
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS builder

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_PYTHON_DOWNLOADS=0
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv_bin /uv /bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

# ---- runtime: slim image without build tools ----
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS runtime

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONPATH=/app/src
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Do not set PORT globally: settings prefer PORT over FLASK_PORT (Cloud Run).
# API compose sets PORT/FLASK_PORT=5000; gunicorn binds $PORT.
ENV FLASK_PORT=5000

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

COPY --from=builder /opt/venv /opt/venv

# Application source only (see .dockerignore)
COPY --chown=appuser:appuser pyproject.toml uv.lock alembic.ini ./
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser main.py dashboard.py streamlit_app.py ./

USER appuser

EXPOSE 5000

# Default: Flask API + native Stitch UI (Cloud Run / generic). Override in compose for worker.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-5000}/livez" || exit 1

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 8 --timeout 330 --graceful-timeout 30 bist_bot.wsgi:app"]
