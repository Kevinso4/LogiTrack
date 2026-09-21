"""Logs JSON y métricas Prometheus del servicio de ingesta.

Sección 9: "especial atención a las métricas del Tracking Ingestion Service
(lecturas GPS por segundo, tasa de error de parseo)".
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

peticiones_total = Counter(
    "tracking_http_requests_total", "Peticiones HTTP", ["metodo", "ruta", "codigo"]
)
peticion_duracion = Histogram(
    "tracking_http_request_duration_seconds", "Duración de las peticiones", ["metodo", "ruta"]
)
lecturas_recibidas = Counter(
    "tracking_lecturas_recibidas_total", "Lecturas GPS recibidas", ["fabricante"]
)
lecturas_aceptadas = Counter(
    "tracking_lecturas_aceptadas_total", "Lecturas GPS persistidas", ["fabricante"]
)
lecturas_rechazadas = Counter(
    "tracking_lecturas_rechazadas_total", "Lecturas descartadas", ["motivo"]
)
lote_duracion = Histogram(
    "tracking_lote_duracion_seconds",
    "Tiempo de proceso de un lote de telemetría",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)
lote_tamano = Histogram(
    "tracking_lote_tamano_lecturas",
    "Lecturas por lote",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 5000),
)
eventos_publicados = Counter(
    "tracking_eventos_publicados_total", "Eventos publicados", ["event_type"]
)
eventos_no_entregados = Counter(
    "tracking_eventos_no_entregados_total",
    "Publicaciones no entregadas en el bus: solo se marca mandatory en "
    "telemetry.aggregated, así que no_enrutado solo puede venir de ahí",
    ["event_type", "motivo"],
)
eventos_fallidos = Counter(
    "tracking_eventos_fallidos_total", "Publicaciones fallidas", ["event_type"]
)
vehiculos_agregados = Gauge(
    "tracking_vehiculos_ultima_ventana",
    "Vehículos con telemetría en la última ventana de agregación",
)


class FormateadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "servicio": "tracking-service",
            "trace_id": trace_id_ctx.get(),
        }
        extra = getattr(record, "contexto", None)
        if isinstance(extra, dict):
            base.update(extra)
        if record.exc_info:
            base["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False, default=str)


def configurar_logging(nivel: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormateadorJSON())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(nivel.upper())
    for ruidoso in ("uvicorn.access", "aio_pika", "aiormq"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def log(logger: logging.Logger, nivel: int, mensaje: str, **contexto: Any) -> None:
    logger.log(nivel, mensaje, extra={"contexto": contexto})


class MiddlewareTrazas(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = trace_id_ctx.set(trace_id)
        inicio = time.perf_counter()
        try:
            respuesta = await call_next(request)
        finally:
            trace_id_ctx.reset(token)
        duracion = time.perf_counter() - inicio
        ruta = request.scope["route"].path if request.scope.get("route") else request.url.path
        peticiones_total.labels(request.method, ruta, respuesta.status_code).inc()
        peticion_duracion.labels(request.method, ruta).observe(duracion)
        respuesta.headers["X-Trace-Id"] = trace_id
        return respuesta


def respuesta_metricas() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
