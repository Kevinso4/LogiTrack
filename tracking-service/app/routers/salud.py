"""Sondas de salud y métricas."""

import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.config import get_settings
from app.database import SessionLocal
from app.observabilidad import respuesta_metricas
from app.schemas import Salud

router = APIRouter(tags=["salud"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=Salud, summary="Liveness")
async def health():
    s = get_settings()
    return Salud(estado="ok", servicio=s.servicio, version=s.version)


@router.get("/ready", response_model=Salud, summary="Readiness")
async def ready(response: Response):
    s = get_settings()
    dependencias = {}
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        dependencias["base_datos"] = "ok"
    except Exception as exc:
        logger.warning("ready.db_error", exc_info=exc)
        dependencias["base_datos"] = "error"

    listo = all(v == "ok" for v in dependencias.values())
    if not listo:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Salud(
        estado="ok" if listo else "degradado",
        servicio=s.servicio,
        version=s.version,
        dependencias=dependencias,
    )


@router.get("/metrics", include_in_schema=False)
async def metrics():
    return respuesta_metricas()
