"""Consumo de eventos del bus.

Fleet escucha dos eventos (matriz de la sección 3):
  * `maintenance.alert`   -> el vehículo pasa a `en_mantenimiento`
  * `shipment.incident`   -> el vehículo pasa a `fuera_de_servicio` (saga)

Ambos manejadores son idempotentes: se registra el `event_id` procesado en la
misma transacción que el cambio, así una reentrega no duplica nada.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.dominio import EstadoVehiculo
from app.events.base import EventoDominio
from app.models import ProcessedEvent, Vehicle
from app.observabilidad import log
from app.servicios import cambiar_estado

logger = logging.getLogger(__name__)

# Severidades de mantenimiento que sacan el vehículo de operación.
SEVERIDADES_BLOQUEANTES = {"alta", "critica", "critical", "high"}
# Tipos de incidencia de envío que implican avería del vehículo.
INCIDENCIAS_DE_VEHICULO = {"averia", "accidente", "vehicle_breakdown", "panne"}


async def _vehiculo_del_evento(session: AsyncSession, evento: EventoDominio) -> Vehicle | None:
    vehicle_id = evento.payload.get("vehicle_id") or evento.payload.get("vehiculo_id")
    if not vehicle_id:
        log(logger, logging.WARNING, "evento.sin_vehicle_id", event_type=evento.event_type)
        return None
    vehiculo = await session.get(Vehicle, vehicle_id)
    if vehiculo is None:
        # El vehículo puede haber sido dado de baja: no es un fallo del consumidor.
        log(
            logger,
            logging.WARNING,
            "evento.vehiculo_inexistente",
            event_type=evento.event_type,
            vehicle_id=vehicle_id,
        )
    return vehiculo


async def manejar_maintenance_alert(session: AsyncSession, evento: EventoDominio) -> None:
    vehiculo = await _vehiculo_del_evento(session, evento)
    if vehiculo is None:
        return
    severidad = str(evento.payload.get("severidad", "alta")).lower()
    if severidad not in SEVERIDADES_BLOQUEANTES:
        log(
            logger,
            logging.INFO,
            "maintenance.alert.ignorada",
            vehicle_id=vehiculo.id,
            severidad=severidad,
        )
        return
    motivo = evento.payload.get("motivo") or f"Alerta de mantenimiento ({severidad})"
    await cambiar_estado(
        session,
        vehiculo,
        EstadoVehiculo.EN_MANTENIMIENTO,
        motivo=motivo,
        origen="maintenance.alert",
        hacer_commit=False,
    )


async def manejar_shipment_incident(session: AsyncSession, evento: EventoDominio) -> None:
    vehiculo = await _vehiculo_del_evento(session, evento)
    if vehiculo is None:
        return
    tipo = str(evento.payload.get("tipo", "averia")).lower()
    confirmado = bool(evento.payload.get("confirmado", True))
    if tipo not in INCIDENCIAS_DE_VEHICULO or not confirmado:
        log(
            logger,
            logging.INFO,
            "shipment.incident.ignorada",
            vehicle_id=vehiculo.id,
            tipo=tipo,
            confirmado=confirmado,
        )
        return
    motivo = evento.payload.get("motivo") or f"Incidencia en ruta: {tipo}"
    await cambiar_estado(
        session,
        vehiculo,
        EstadoVehiculo.FUERA_DE_SERVICIO,
        motivo=motivo,
        origen="shipment.incident",
        hacer_commit=False,
    )


MANEJADORES: Dict[str, Callable[[AsyncSession, EventoDominio], Awaitable[None]]] = {
    "maintenance.alert": manejar_maintenance_alert,
    "shipment.incident": manejar_shipment_incident,
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
