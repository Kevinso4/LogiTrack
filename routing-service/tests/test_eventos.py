"""Consumidor del bus: manejadores, deduplicación por event_id y recálculo
por vehicle.status_changed."""

from app.database import SessionLocal
from app.dominio import EstadoRuta
from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.models import ProcessedEvent, Ruta
from sqlalchemy import select


async def test_shipment_created_asigna_ruta(evento_shipment_created):
    evento = EventoDominio(
        event_id="evt-1", event_type="shipment.created", payload=evento_shipment_created["payload"]
    )
    await manejar_evento(evento)
    async with SessionLocal() as session:
        ruta = await session.scalar(select(Ruta))
        assert ruta is not None
        assert ruta.estado == EstadoRuta.ASIGNADA.value
        assert await session.get(ProcessedEvent, "evt-1") is not None


async def test_reenvio_duplicado_no_crea_segunda_ruta(evento_shipment_created, cliente_fleet):
    evento = EventoDominio(
        event_id="evt-dup",
        event_type="shipment.created",
        payload=evento_shipment_created["payload"],
    )
    await manejar_evento(evento)
    await manejar_evento(evento)  # reentrega idéntica
    async with SessionLocal() as session:
        rutas = (await session.execute(select(Ruta))).scalars().all()
        assert len(rutas) == 1
    cliente_fleet.llamadas == 1
    assert cliente_fleet.llamadas == 1  # el duplicado ni consultó a Fleet


async def test_vehicle_status_fuera_servicio_recalcula(
    evento_shipment_created, evento_vehicle_status, cliente_fleet
):
    cliente_fleet._vehiculos.append(
        cliente_fleet._vehiculos[0].model_copy(update={"id": "v-002", "plate": "ABC111"})
    )
    await manejar_evento(
        EventoDominio(
            event_id="evt-created",
            event_type="shipment.created",
            payload=evento_shipment_created["payload"],
        )
    )
    cliente_fleet._vehiculos = [v for v in cliente_fleet._vehiculos if v.id != "v-001"]
    await manejar_evento(
        EventoDominio(
            event_id="evt-status",
            event_type="vehicle.status_changed",
            payload=evento_vehicle_status["payload"],
        )
    )
    async with SessionLocal() as session:
        ruta = (await session.execute(select(Ruta))).scalars().first()
        assert ruta.vehicle_id == "v-002"
        assert ruta.estado == EstadoRuta.RECALCULADA.value


async def test_vehicle_status_ocuoso_no_recalcula(evento_shipment_created, cliente_fleet):
    cliente_fleet._vehiculos.append(cliente_fleet._vehiculos[0].model_copy(update={"id": "v-002"}))
    await manejar_evento(
        EventoDominio(
            event_id="evt-creado",
            event_type="shipment.created",
            payload=evento_shipment_created["payload"],
        )
    )
    await manejar_evento(
        EventoDominio(
            event_id="evt-ocio",
            event_type="vehicle.status_changed",
            payload={
                "vehicle_id": "v-001",
                "estado_anterior": "fuera_de_servicio",
                "estado_nuevo": "activo",
            },
        )
    )
    async with SessionLocal() as session:
        ruta = (await session.execute(select(Ruta))).scalars().first()
        assert ruta.vehicle_id == "v-001"
        assert ruta.estado == EstadoRuta.ASIGNADA.value


async def test_tipo_de_evento_desconocido_no_rompe_el_consumidor():
    evento = EventoDominio(event_id="evt-x", event_type="desconocido.marciano", payload={})
    await manejar_evento(evento)
    async with SessionLocal() as session:
        assert await session.get(ProcessedEvent, "evt-x") is not None


async def test_payload_ilegal_no_crashea_y_se_marca_como_procesado():
    evento = EventoDominio(
        event_id="evt-malo",
        event_type="shipment.created",
        payload={"shipment_id": "s-1"},  # falta peso/origen/destino
    )
    await manejar_evento(evento)
    async with SessionLocal() as session:
        assert await session.get(ProcessedEvent, "evt-malo") is not None
        assert (await session.execute(select(Ruta))).scalars().first() is None
