"""Tests del bus: outbox, consumo de eventos e idempotencia."""

from sqlalchemy import select

from app.database import SessionLocal
from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.models import OutboxEvent, Vehicle


async def _crear_vehiculo(cliente, datos):
    return (await cliente.post("/api/v1/vehiculos", json=datos)).json()


async def test_cambio_estado_encola_y_publica_evento(cliente, vehiculo_valido, bus):
    publicador, relay = bus
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)

    await cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado",
        json={"estado": "en_transito", "motivo": "ruta 40 asignada"},
    )

    # El evento queda en el outbox, todavía sin publicar.
    async with SessionLocal() as session:
        pendientes = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))))
            .scalars()
            .all()
        )
    assert len(pendientes) == 1
    assert pendientes[0].event_type == "vehicle.status_changed"

    # El relay lo publica y lo marca como enviado.
    enviados = await relay.despachar_pendientes()
    assert enviados == 1

    publicados = publicador.por_tipo("vehicle.status_changed")
    assert len(publicados) == 1
    payload = publicados[0].payload
    assert payload["vehicle_id"] == vehiculo["id"]
    assert payload["estado_anterior"] == "activo"
    assert payload["estado_nuevo"] == "en_transito"
    assert payload["asignable"] is False

    async with SessionLocal() as session:
        restantes = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))))
            .scalars()
            .all()
        )
    assert restantes == []


async def test_estado_repetido_no_genera_segundo_evento(cliente, vehiculo_valido):
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)
    for _ in range(3):
        await cliente.patch(
            f"/api/v1/vehiculos/{vehiculo['id']}/estado", json={"estado": "en_transito"}
        )
    async with SessionLocal() as session:
        eventos = (await session.execute(select(OutboxEvent))).scalars().all()
    assert len(eventos) == 1


async def test_maintenance_alert_pone_el_vehiculo_en_mantenimiento(cliente, vehiculo_valido, bus):
    publicador, relay = bus
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)

    evento = EventoDominio(
        event_type="maintenance.alert",
        producer="maintenance-service",
        payload={
            "vehicle_id": vehiculo["id"],
            "severidad": "critica",
            "motivo": "temperatura de motor sobre umbral",
        },
    )
    await manejar_evento(evento)

    ficha = (await cliente.get(f"/api/v1/vehiculos/{vehiculo['id']}")).json()
    assert ficha["status"] == "en_mantenimiento"
    assert ficha["motivo_estado"] == "temperatura de motor sobre umbral"

    await relay.despachar_pendientes()
    publicado = publicador.por_tipo("vehicle.status_changed")[0]
    assert publicado.payload["origen"] == "maintenance.alert"


async def test_maintenance_alert_de_baja_severidad_no_cambia_nada(cliente, vehiculo_valido):
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)
    await manejar_evento(
        EventoDominio(
            event_type="maintenance.alert",
            payload={"vehicle_id": vehiculo["id"], "severidad": "baja"},
        )
    )
    ficha = (await cliente.get(f"/api/v1/vehiculos/{vehiculo['id']}")).json()
    assert ficha["status"] == "activo"


async def test_shipment_incident_deja_el_vehiculo_fuera_de_servicio(cliente, vehiculo_valido):
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)
    await manejar_evento(
        EventoDominio(
            event_type="shipment.incident",
            producer="shipment-service",
            payload={
                "vehicle_id": vehiculo["id"],
                "shipment_id": "env-001",
                "tipo": "averia",
                "confirmado": True,
            },
        )
    )
    ficha = (await cliente.get(f"/api/v1/vehiculos/{vehiculo['id']}")).json()
    assert ficha["status"] == "fuera_de_servicio"


async def test_evento_reentregado_es_idempotente(cliente, vehiculo_valido):
    vehiculo = await _crear_vehiculo(cliente, vehiculo_valido)
    evento = EventoDominio(
        event_type="maintenance.alert",
        payload={"vehicle_id": vehiculo["id"], "severidad": "alta"},
    )
    await manejar_evento(evento)
    await manejar_evento(evento)  # misma entrega, misma event_id

    async with SessionLocal() as session:
        eventos = (await session.execute(select(OutboxEvent))).scalars().all()
    assert len(eventos) == 1  # un solo vehicle.status_changed


async def test_evento_con_vehiculo_inexistente_no_rompe_el_consumidor():
    await manejar_evento(
        EventoDominio(
            event_type="maintenance.alert",
            payload={"vehicle_id": "fantasma", "severidad": "critica"},
        )
    )
    async with SessionLocal() as session:
        assert (await session.execute(select(Vehicle))).scalars().all() == []
