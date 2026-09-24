"""Formato único de error y middleware de request_id, compartidos por todos los servicios."""
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logs import request_id_var

log = logging.getLogger("http")

_CODIGOS = {
    400: "peticion_invalida",
    401: "no_autenticado",
    403: "sin_permiso",
    404: "no_encontrado",
    409: "conflicto",
    422: "entrada_invalida",
    429: "limite_excedido",
    503: "servicio_no_disponible",
}


def error(status: int, codigo: str, mensaje: str) -> HTTPException:
    """Crea una HTTPException con el formato de error de LogiTrack. Se usa con `raise error(...)`."""
    return HTTPException(status_code=status, detail={"error": codigo, "mensaje": mensaje})


def cuerpo_error(codigo: str, mensaje: str, detalles=None) -> dict:
    cuerpo = {
        "error": codigo,
        "mensaje": mensaje,
        "request_id": request_id_var.get(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if detalles:
        cuerpo["detalles"] = detalles
    return cuerpo


def instalar_manejadores(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_y_log(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        inicio = time.perf_counter()
        try:
            respuesta = await call_next(request)
            respuesta.headers["X-Request-ID"] = rid
            if request.url.path not in ("/health", "/ready"):
                log.info(
                    "%s %s -> %s",
                    request.method,
                    request.url.path,
                    respuesta.status_code,
                    extra={
                        "metodo": request.method,
                        "ruta": request.url.path,
                        "estado_http": respuesta.status_code,
                        "duracion_ms": round((time.perf_counter() - inicio) * 1000, 1),
                    },
                )
            return respuesta
        finally:
            request_id_var.reset(token)

    # StarletteHTTPException también cubre los 404/405 de rutas inexistentes.
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            cuerpo = cuerpo_error(exc.detail["error"], exc.detail.get("mensaje", ""))
        else:
            cuerpo = cuerpo_error(_CODIGOS.get(exc.status_code, "error"), str(exc.detail))
        return JSONResponse(cuerpo, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validacion(_: Request, exc: RequestValidationError):
        detalles = [
            {"campo": ".".join(str(p) for p in e["loc"][1:]), "mensaje": e["msg"]} for e in exc.errors()
        ]
        return JSONResponse(
            cuerpo_error("entrada_invalida", "La petición tiene datos inválidos", detalles), status_code=422
        )

    @app.exception_handler(Exception)
    async def inesperado(_: Request, exc: Exception):
        log.exception("Error no controlado")
        return JSONResponse(cuerpo_error("error_interno", "Ocurrió un error inesperado"), status_code=500)
