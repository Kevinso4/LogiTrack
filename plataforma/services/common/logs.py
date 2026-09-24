"""Logs estructurados en JSON, una línea por evento."""
import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_CAMPOS_EXTRA = ("shipment_id", "vehicle_id", "evento", "routing_key", "ruta", "metodo", "estado_http", "duracion_ms")


class JsonFormatter(logging.Formatter):
    def __init__(self, servicio: str):
        super().__init__()
        self.servicio = servicio

    def format(self, record: logging.LogRecord) -> str:
        datos = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "servicio": self.servicio,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "mensaje": record.getMessage(),
        }
        for campo in _CAMPOS_EXTRA:
            if hasattr(record, campo):
                datos[campo] = getattr(record, campo)
        if record.exc_info:
            datos["error"] = self.formatException(record.exc_info)
        return json.dumps(datos, ensure_ascii=False, default=str)


def configurar_logs(servicio: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(servicio))
    raiz = logging.getLogger()
    raiz.handlers = [handler]
    raiz.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    for ruidoso in ("aio_pika", "aiormq", "httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
