"""Logs JSON correlacionados y métricas Prometheus.

Sección 9 del documento: logs centralizados en formato JSON con correlación
por `vehicle_id` / `shipment_id` / `trace_id` para poder reconstruir la
trazabilidad completa de cualquier incidencia.
"""

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Dict

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")

peticiones_total = Counter(
    "fleet_http_requests_total",
    "Peticiones HTTP atendidas",
    ["metodo", "ruta", "codigo"],
)
peticion_duracion = Histogram(
    "fleet_http_request_duration_seconds",
    "Duración de las peticiones HTTP",
    ["metodo", "ruta"],
)
eventos_publicados = Counter(
    "fleet_eventos_publicados_total", "Eventos publicados al bus", ["event_type"]
)
eventos_consumidos = Counter(
    "fleet_eventos_consumidos_total",
    "Eventos consumidos del bus",
    ["event_type", "resultado"],
)
eventos_no_entregados = Counter(
    "fleet_eventos_no_entregados_total",
    "Publicaciones no entregadas en el bus: no_enrutado = mandatory devuelto, "
    "conexion = broker inaccesible",
    ["event_type", "motivo"],
)
cambios_estado = Counter(
    "fleet_cambios_estado_total",
    "Cambios de estado de vehículo",
    ["desde", "hacia", "origen"],
)


class FormateadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "servicio": "fleet-service",
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
    """Atajo para emitir un log con contexto estructurado."""
    logger.log(nivel, mensaje, extra={"contexto": contexto})


class MiddlewareTrazas(BaseHTTPMiddleware):
    """Propaga `X-Trace-Id` (lo inyecta el API Gateway) y mide cada petición."""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        token = trace_id_ctx.set(trace_id)
        ruta = request.scope.get("route").path if request.scope.get("route") else request.url.path
        inicio = time.perf_counter()
        try:
            respuesta = await call_next(request)
        finally:
            trace_id_ctx.reset(token)
        duracion = time.perf_counter() - inicio
        ruta = request.scope["route"].path if request.scope.get("route") else ruta
        peticiones_total.labels(request.method, ruta, respuesta.status_code).inc()
        peticion_duracion.labels(request.method, ruta).observe(duracion)
        respuesta.headers["X-Trace-Id"] = trace_id
        return respuesta


def respuesta_metricas() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
