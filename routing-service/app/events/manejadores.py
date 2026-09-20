"""Consumo de eventos del bus.

Routing escucha tres eventos (matriz de la sección 3):
  * `shipment.created`         -> primera asignación de ruta
  * `telemetry.aggregated`     -> ETA de recuperación (detección de desvío)
  * `vehicle.status_changed`   -> recálculo si el vehículo sale de operación

Todos los manejadores son idempotentes: se registra el `event_id` procesado en
la misma transacción que el cambio, así una reentrega no duplica nada.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.dominio import ESTADOS_ACTIVOS
from app.events.base import EventoDominio
from app.models import ProcessedEvent, Ruta
from app.observabilidad import log
from app.schemas import (
    ShipmentCreatedPayload,
    TelemetryAggregatedPayload,
    VehicleStatusChangedPayload,
)
from app.servicios import (
    asignar_ruta,
    actualizar_por_telemetria,
    recalcular_ruta,
)

logger = logging.getLogger(__name__)

# Estados de Fleet (vehicle.status_changed) que obligan a recalcular la ruta.
ESTADOS_FUERA_OPERACION = {"en_mantenimiento", "fuera_de_servicio"}


async def manejar_shipment_created(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = ShipmentCreatedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(
            logger,
            logging.WARNING,
            "shipment.created.ilegal",
            event_id=evento.event_id,
            error=str(exc),
        )
        return
    await asignar_ruta(session, payload, hacer_commit=False)


async def manejar_telemetry_aggregated(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = TelemetryAggregatedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(
            logger,
            logging.WARNING,
            "telemetry.aggregated.ilegal",
            event_id=evento.event_id,
            error=str(exc),
        )
        return
    await actualizar_por_telemetria(session, payload, hacer_commit=False)


async def manejar_vehicle_status_changed(session: AsyncSession, evento: EventoDominio) -> None:
    try:
        payload = VehicleStatusChangedPayload.model_validate(evento.payload)
    except ValidationError as exc:
        log(
            logger,
            logging.WARNING,
            "vehicle.status_changed.ilegal",
            event_id=evento.event_id,
            error=str(exc),
        )
        return
    if payload.estado_nuevo not in ESTADOS_FUERA_OPERACION:
        return

    rutas = (
        (
            await session.execute(
                select(Ruta)
                .where(
                    Ruta.vehicle_id == payload.vehicle_id,
                    Ruta.estado.in_([s.value for s in ESTADOS_ACTIVOS]),
                )
                .order_by(Ruta.actualizada_en.desc())
            )
        )
        .scalars()
        .all()
    )
    for ruta in rutas:
        await recalcular_ruta(
            session,
            ruta.id,
            causa=f"vehicle.status_changed:{payload.estado_nuevo}",
            excluir_vehicle_id=payload.vehicle_id,
            hacer_commit=False,
        )


MANEJADORES: Dict[str, Callable[[AsyncSession, EventoDominio], Awaitable[None]]] = {
    "shipment.created": manejar_shipment_created,
    "telemetry.aggregated": manejar_telemetry_aggregated,
    "vehicle.status_changed": manejar_vehicle_status_changed,
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
