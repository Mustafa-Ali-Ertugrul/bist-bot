FROM python:3.11-slim as builder

ARG CACHE_BUST
RUN echo "cache-bust=${CACHE_BUST}"

WORKDIR /app
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv "$VIRTUAL_ENV"     && pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
COPY --from=builder /opt/venv /opt/venv
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y --no-install-recommends     curl     && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8501 5000

CMD ["sh", "-c", "streamlit run streamlit_app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
