"""Logs JSON correlacionados.

El puente no tiene base de datos; la observabilidad se reduce a logs JSON con
correlación por `trace_id` / `event_id`, igual que los demás servicios.
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="-")


class FormateadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
            "servicio": "interop-bridge",
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
