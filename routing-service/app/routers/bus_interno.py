"""Endpoint de DEMO para inyectar eventos directamente (artefacto LOCAL).

NO forma parte del producto: se monta solo si el servicio arranca con
`DEMO_BUS_INTERNO=true` y en un entorno fuera de producción/Docker. Sustituye
al broker en el arranque local, pues RabbitMQ no está disponible sin Docker.

Delega en la MISMA carretera de entrada que el consumidor de RabbitMQ
(`manejar_evento`), de modo que la deduplicación por `event_id` se demuestra
de verdad: entregar dos veces el mismo evento no aplica cambios dos veces.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.observabilidad import log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/bus", tags=["demo-interna"])


@router.post("/deliver", include_in_schema=False)
async def entregar(evento: EventoDominio) -> dict:
    if not evento.event_type:
        raise HTTPException(status_code=422, detail="event_type es obligatorio")
    await manejar_evento(evento)
    log(logger, logging.INFO, "demo.evento_entregado", event_type=evento.event_type)
    return {"entregado": True, "event_id": evento.event_id}
