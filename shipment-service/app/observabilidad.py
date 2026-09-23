"""Logs JSON correlacionados y métricas Prometheus.

Mismos convenios que el resto del stack (sección 9 del documento): logs
centralizados en formato JSON con correlación por `vehicle_id` / `shipment_id`
/ `trace_id`, y métricas con el prefijo `shipment_`.
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
    "shipment_http_requests_total",
    "Peticiones HTTP atendidas",
    ["metodo", "ruta", "codigo"],
)
peticion_duracion = Histogram(
    "shipment_http_request_duration_seconds",
    "Duración de las peticiones HTTP",
    ["metodo", "ruta"],
)
eventos_publicados = Counter(
    "shipment_eventos_publicados_total", "Eventos publicados al bus", ["event_type"]
)
eventos_consumidos = Counter(
    "shipment_eventos_consumidos_total",
    "Eventos consumidos del bus",
    ["event_type", "resultado"],
)
eventos_no_entregados = Counter(
    "shipment_eventos_no_entregados_total",
    "Publicaciones no entregadas en el bus: no_enrutado = mandatory devuelto, "
    "conexion = broker inaccesible",
    ["event_type", "motivo"],
)
outbox_agotados = Counter(
    "shipment_outbox_eventos_agotados_total",
    "Eventos que rebasaron outbox_max_intentos: siguen reintentando con "
    "backoff; debe acercarse a cero cuando el bus está sano",
)
envios_creados = Counter(
    "shipment_envios_creados_total", "Envíos creados en total", ["internacional"]
)
envios_transicionados = Counter(
    "shipment_envios_transicionados_total",
    "Transiciones de estado de envío",
    ["desde", "hasta"],
)


class FormateadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: Dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "servicio": "shipment-service",
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
    """Propaga `X-Trace-Id` (la reutiliza o la genera si no llega) y mide cada petición.

    Un futuro API Gateway sería quien la inyecte en el borde.
    """

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
        peticiones_total.labels(request.method, ruta, respuesta.status_code).inc()
        peticion_duracion.labels(request.method, ruta).observe(duracion)
        respuesta.headers["X-Trace-Id"] = trace_id
        return respuesta


def respuesta_metricas() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
