# syntax=docker/dockerfile:1
# Build multi-stage: la imagen final no lleva compilador ni caché de pip.
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Sin root dentro del contenedor.
RUN useradd --create-home --uid 10001 logitrack
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=logitrack:logitrack . .

RUN chmod +x entrypoint.sh
USER logitrack
EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8004/health/live').status==200 else 1)"

ENTRYPOINT ["./entrypoint.sh"]