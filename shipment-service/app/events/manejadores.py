"""Consumo de eventos del bus.

Shipment escucha cinco eventos (matriz de la sección 3 + desvío documentado):
  * `route.assigned`        -> el envío sale a ruta (en_ruta, ETA del envío)
  * `route.recalculated`    -> vehículo/ETA actualizados
  * `route.unassignable`    -> pasamos a `retrasado` y publicamos shipment.delayed
  * `customs.held`          -> retenido en aduana (en_ruta -> retenido_aduanera)
  * `customs.cleared`       -> vuelve a ruta (retenido_aduanera -> en_ruta)

Todos los manejadores son idempotentes por `event_id` (processed_events) y
todas las transiciones pasan por la máquina de estados del dominio.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.events.base import EventoDominio
from app.models import ProcessedEvent
from app.observabilidad import log
from app.schemas import (
    CustomsClearedPayload,
    CustomsHeldPayload,
    RouteAssignedPayload,
    RouteRecalculatedPayload,
    RouteUnassignablePayload,
)
from app.servicios import (
    aplicar_customs_cleared,
    aplicar_customs_held,
    aplicar_route_assigned,
    aplicar_route_recalculated,
    aplicar_route_unassignable,
)

logger = logging.getLogger(__name__)


async def manejar_route_assigned(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = RouteAssignedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(logger, logging.WARNING, "route.assigned.ilegal", error=str(exc))
        return
    try:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
    except Exception as exc:  # RecursoNoEncontrado: mensaje mal encaminado
        log(logger, logging.WARNING, "route.assigned.rechazado", error=str(exc))


async def manejar_route_recalculated(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = RouteRecalculatedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(logger, logging.WARNING, "route.recalculated.ilegal", error=str(exc))
        return
    try:
        await aplicar_route_recalculated(session, payload, hacer_commit=False)
    except Exception as exc:
        log(logger, logging.WARNING, "route.recalculated.rechazado", error=str(exc))


async def manejar_route_unassignable(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = RouteUnassignablePayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(logger, logging.WARNING, "route.unassignable.ilegal", error=str(exc))
        return
    try:
        await aplicar_route_unassignable(session, payload, hacer_commit=False)
    except Exception as exc:
        log(logger, logging.WARNING, "route.unassignable.rechazado", error=str(exc))


async def manejar_customs_held(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = CustomsHeldPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(logger, logging.WARNING, "customs.held.ilegal", error=str(exc))
        return
    try:
        await aplicar_customs_held(session, payload, hacer_commit=False)
    except Exception as exc:
        log(logger, logging.WARNING, "customs.held.rechazado", error=str(exc))


async def manejar_customs_cleared(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = CustomsClearedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(logger, logging.WARNING, "customs.cleared.ilegal", error=str(exc))
        return
    try:
        await aplicar_customs_cleared(session, payload, hacer_commit=False)
    except Exception as exc:
        log(logger, logging.WARNING, "customs.cleared.rechazado", error=str(exc))


MANEJADORES: Dict[str, Callable[[AsyncSession, EventoDominio], Awaitable[None]]] = {
    "route.assigned": manejar_route_assigned,
    "route.recalculated": manejar_route_recalculated,
    "route.unassignable": manejar_route_unassignable,
    "customs.held": manejar_customs_held,
    "customs.cleared": manejar_customs_cleared,
}


async def manejar_evento(evento: EventoDominio) -> None:
    """Punto de entrada del consumidor: deduplica, aplica y confirma."""
    async with SessionLocal() as session:
        if await session.get(ProcessedEvent, evento.event_id):
            log(
                logger,
                logging.INFO,
                "evento.duplicado_ignorado",
                event_id=evento.event_id,
                event_type=evento.event_type,
            )
            return

        manejador = MANEJADORES.get(evento.event_type)
        if manejador is not None:
            await manejador(session, evento)

        session.add(ProcessedEvent(event_id=evento.event_id, event_type=evento.event_type))
        # Efecto de negocio + marca de procesado + evento de salida: un commit.
        await session.commit()
