# Plantilla única de Dockerfile para todos los microservicios (multi-etapa).
#   docker build --build-arg SERVICE=fleet -t logitrack-fleet ./services
ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:${PYTHON_VERSION}-slim
ARG SERVICE
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY common ./common
COPY ${SERVICE} ./service
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
