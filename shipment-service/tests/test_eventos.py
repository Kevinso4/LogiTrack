"""Consumidor del bus: manejadores y deduplicación por event_id."""

from app.database import SessionLocal
from app.dominio import EstadoEnvio
from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.models import Envio, HistorialEnvio, ProcessedEvent
from app.schemas import EnvioRequest
from sqlalchemy import select


async def test_el_mismo_route_assigned_entregado_dos_veces_es_idempotente(
    envio_valido, evento_route_assigned
):
    from app.servicios import crear_envio

    async with SessionLocal() as session:
        envio = await crear_envio(session, EnvioRequest.model_validate(envio_valido))
        evento_route_assigned["payload"]["shipment_id"] = envio.id

    evento = EventoDominio(
        event_id="evt-ruta-1",
        event_type="route.assigned",
        payload=evento_route_assigned["payload"],
    )
    await manejar_evento(evento)
    await manejar_evento(evento)  # reentrega idéntica

    async with SessionLocal() as session:
        envio = (await session.execute(select(Envio))).scalars().first()
        assert envio.estado == EstadoEnvio.EN_RUTA.value
        assert await session.get(ProcessedEvent, "evt-ruta-1") is not None
        huellas = (await session.execute(select(HistorialEnvio))).scalars().all()
        # Una sola transición en_almacen -> en_ruta
        assert len([h for h in huellas if h.hasta == EstadoEnvio.EN_RUTA.value]) == 1


async def test_tipo_de_evento_desconocido_no_rompe_el_consumidor():
    await manejar_evento(EventoDominio(event_id="evt-x", event_type="alien.señal", payload={}))
    async with SessionLocal() as session:
        assert await session.get(ProcessedEvent, "evt-x") is not None


async def test_payload_ilegal_no_crashea_y_se_marca_como_procesado(
    envio_valido, evento_route_assigned
):
    evento = EventoDominio(
        event_id="evt-malo",
        event_type="route.assigned",
        payload={"ruta_id": "r-1"},  # falta shipment_id y el resto
    )
    await manejar_evento(evento)
    async with SessionLocal() as session:
        assert await session.get(ProcessedEvent, "evt-malo") is not None
        # No se tocó ningún envío.
        assert (await session.execute(select(Envio))).scalars().all() == []


async def test_route_unassignable_por_el_canal_retrasa_el_envio(
    envio_valido, evento_route_unassignable
):
    from app.servicios import crear_envio

    async with SessionLocal() as session:
        envio = await crear_envio(session, EnvioRequest.model_validate(envio_valido))
        evento_route_unassignable["payload"]["shipment_id"] = envio.id
    await manejar_evento(
        EventoDominio(
            event_id="evt-unas",
            event_type="route.unassignable",
            payload=evento_route_unassignable["payload"],
        )
    )
    async with SessionLocal() as session:
        envio = (await session.execute(select(Envio))).scalars().first()
        assert envio.estado == EstadoEnvio.RETRASADO.value
        assert envio.motivo == "sin vehículo viable"


async def test_evento_para_envio_inexistente_se_descarta_sin_crashear(
    evento_route_assigned,
):
    evento = EventoDominio(
        event_id="evt-fantasma",
        event_type="route.assigned",
        payload=evento_route_assigned["payload"],  # shipment_id s-1001 no existe
    )
    await manejar_evento(evento)
    async with SessionLocal() as session:
        assert await session.get(ProcessedEvent, "evt-fantasma") is not None
