"""Health checks: liveness (proceso vivo) y readiness (dependencias).

El readiness distingue "dependencia crítica" de "mejorable": el bus (no
crítico) no tira abajo `/ready`; la base de datos sí.

Convención unificada del sistema: `/health` y `/ready` (la de la mayoría y la
más corta). `/health/live` y `/health/ready` quedan como alias mientras los
healthchecks de Docker y el demo sigan apuntando ahí.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.database import SessionLocal
from app.observabilidad import respuesta_metricas

logger = logging.getLogger(__name__)

router = APIRouter(tags=["salud"])


@router.get("/health", summary="Liveness: proceso vivo (convención del sistema)")
@router.get("/health/live", summary="Liveness: proceso vivo (alias)")
async def vivir() -> dict:
    return {"estado": "vivo", "servicio": "shipment-service"}


@router.get("/ready", summary="Readiness: dependencias listas (convención del sistema)")
@router.get("/health/ready", summary="Readiness: dependencias listas (alias)")
async def listo() -> dict:
    dependencias = {"basedatos": "sano"}
    try:
        async with SessionLocal() as sesion:
            await sesion.execute(text("SELECT 1"))
    except Exception:
        dependencias["basedatos"] = "enfermo"
        logger.exception("health.basedatos.error")
    return {
        "estado": "listo" if dependencias["basedatos"] == "sano" else "no_listo",
        "dependencias": dependencias,
    }


@router.get("/metrics", include_in_schema=False)
async def metricas():
    return respuesta_metricas()
