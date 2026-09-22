"""Health checks del puente.

Liveness: proceso vivo. Readiness: el puente está suscrito y alistado en el
bus (`puente.activo`). El bus es la única dependencia del bridge: sin él no
traduce nada.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.observabilidad import log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["salud"])


@router.get("/health/live", summary="Liveness: proceso vivo")
async def vivir() -> dict:
    return {"estado": "vivo", "servicio": "interop-bridge"}


@router.get("/health/ready", summary="Readiness: puente alistado en el bus")
async def listo(request: Request) -> dict:
    puente = getattr(request.app.state, "puente", None)
    activo = bool(puente and puente.activo)
    log(logger, logging.INFO, "health.puente", activo=activo)
    return {
        "estado": "listo" if activo else "no_listo",
        "dependencias": {"bus": "sano" if activo else "enfermo"},
    }
