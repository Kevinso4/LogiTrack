"""Health checks: liveness (proceso vivo) y readiness (dependencias).

El readiness distingue "dependencia crítica" de "mejorable": Redis y el bus
(no críticos) no tiran abajo `/health/ready`; la base de datos sí.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.database import SessionLocal
from app.observabilidad import respuesta_metricas

logger = logging.getLogger(__name__)

router = APIRouter(tags=["salud"])


@router.get("/health/live", summary="Liveness: proceso vivo")
async def vivir() -> dict:
    return {"estado": "vivo", "servicio": "routing-service"}


@router.get("/health/ready", summary="Readiness: dependencias listas")
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
