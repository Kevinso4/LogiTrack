"""Errores de aplicación y su traducción a un formato de respuesta único."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.observabilidad import trace_id_ctx


class ErrorAplicacion(Exception):
    codigo_http = 400
    codigo = "error_aplicacion"

    def __init__(self, mensaje: str, detalles: dict | None = None):
        self.mensaje = mensaje
        self.detalles = detalles or {}
        super().__init__(mensaje)


class RecursoNoEncontrado(ErrorAplicacion):
    codigo_http = 404
    codigo = "recurso_no_encontrado"


class ConflictoRecurso(ErrorAplicacion):
    codigo_http = 409
    codigo = "conflicto"


class ReglaNegocioViolada(ErrorAplicacion):
    codigo_http = 422
    codigo = "regla_negocio"


async def manejador_error_aplicacion(_: Request, exc: ErrorAplicacion) -> JSONResponse:
    return JSONResponse(
        status_code=exc.codigo_http,
        content={
            "error": exc.codigo,
            "mensaje": exc.mensaje,
            "detalles": exc.detalles,
            "trace_id": trace_id_ctx.get(),
        },
    )
