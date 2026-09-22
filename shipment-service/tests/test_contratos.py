"""Contratos publicados por Shipment contra los fixtures de CONTRATOS.md.

Verificación en dos capas:

1. El sobre del fixture parsea con `EventoDominio` y su conjunto de claves es
   exactamente el del sobre publicado.
2. El camino real de producción (`crear_envio`, `incidente`, `entregar`,
   `devolver`, `route.unassignable`) escribe en el outbox payloads cuyo
   conjunto de claves coincide con los fixtures — los tests de CONTRATOS.
"""

import json
import pathlib

from sqlalchemy import select

from app.database import SessionLocal
from app.events.base import EventoDominio
from app.models import Envio, OutboxEvent
from app.schemas import (
    EnvioRequest,
    PruebaEntregaRequest,
    RouteAssignedPayload,
    RouteUnassignablePayload,
)
from app.servicios import (
    aplicar_route_assigned,
    aplicar_route_unassignable,
    crear_envio,
    devolver,
    entregar,
    incidente,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SOBRE_PROPIO = {"event_id", "event_type", "occurred_at", "producer", "trace_id", "payload"}


def _leer_fixture(nombre: str) -> dict:
    with open(FIXTURES / nombre, encoding="utf-8") as fh:
        return json.load(fh)


async def _crear_envio_en_almacen(envio_valido):
    async with SessionLocal() as session:
        envio = await crear_envio(session, EnvioRequest.model_validate(envio_valido))
        return envio


async def _enviar_a_ruta(envio: Envio):
    async with SessionLocal() as session:
        await aplicar_route_assigned(
            session,
            RouteAssignedPayload(
                ruta_id="r-1",
                shipment_id=envio.id,
                vehicle_id="v-9a4c",
                vehicle_plate="ABC-123",
                eta=None,
            ),
        )
        return envio


async def _outbox(event_type: str):
    async with SessionLocal() as session:
        fila = await session.scalar(select(OutboxEvent).where(OutboxEvent.event_type == event_type))
        return fila


def test_fixtures_parsean_y_tienen_el_sobre_exacto():
    for nombre in (
        "shipment.created.json",
        "shipment.incident.json",
        "shipment.delivered.json",
        "shipment.returned.json",
        "shipment.delayed.json",
    ):
        fixture = _leer_fixture(nombre)
        evento = EventoDominio.desde_bytes(json.dumps(fixture).encode("utf-8"))
        assert set(evento.model_dump(mode="json")) == SOBRE_PROPIO, nombre


async def test_produccion_shipment_created_coincide_con_el_fixture(envio_valido):
    fixture = _leer_fixture("shipment.created.json")
    envio = await _crear_envio_en_almacen(envio_valido)
    fila = await _outbox("shipment.created")

    assert fila is not None
    assert set(fila.payload) == set(fixture["payload"])
    # Valores fijos del contrato se conservan tal cual.
    assert fila.payload["peso_kg"] == 8000
    assert fila.payload["volumen_m3"] == 20
    assert fila.payload["requiere_refrigeracion"] is True
    assert set(fila.payload["origen"]) == {"lat", "lon", "direccion"}
    assert envio.estado == "en_almacen"


async def test_produccion_shipment_incident_coincide_con_el_fixture(envio_valido):
    fixture = _leer_fixture("shipment.incident.json")
    envio = await _crear_envio_en_almacen(envio_valido)
    await _enviar_a_ruta(envio)
    async with SessionLocal() as session:
        await incidente(session, envio.id, "averia", confirmado=True, motivo="falla hidráulica")
    fila = await _outbox("shipment.incident")

    assert set(fila.payload) == set(fixture["payload"])
    assert fila.payload["tipo"] == "averia"
    assert fila.payload["confirmado"] is True
    assert fila.payload["vehicle_id"] == "v-9a4c"


async def test_produccion_shipment_delivered_coincide_con_el_fixture(envio_valido):
    fixture = _leer_fixture("shipment.delivered.json")
    envio = await _crear_envio_en_almacen(envio_valido)
    await _enviar_a_ruta(envio)
    async with SessionLocal() as session:
        await entregar(session, envio.id, PruebaEntregaRequest(nombre_recibe="Ana García"))
    fila = await _outbox("shipment.delivered")

    assert set(fila.payload) == set(fixture["payload"])
    assert fila.payload["destinatario"] == "Ana García"
    assert fila.payload["vehicle_plate"] == "ABC-123"
    assert fila.payload["entregado_en"]  # ISO con zona horaria


async def test_produccion_shipment_returned_coincide_con_el_fixture(envio_valido):
    fixture = _leer_fixture("shipment.returned.json")
    envio = await _crear_envio_en_almacen(envio_valido)
    await _enviar_a_ruta(envio)  # retornado solo es legal desde en_transito/en_ruta
    async with SessionLocal() as session:
        await devolver(session, envio.id, motivo="dirección sin acceso")
    fila = await _outbox("shipment.returned")

    assert set(fila.payload) == set(fixture["payload"])
    assert fila.payload["motivo"] == "dirección sin acceso"


async def test_produccion_shipment_delayed_coincide_con_el_fixture(envio_valido):
    fixture = _leer_fixture("shipment.delayed.json")
    envio = await _crear_envio_en_almacen(envio_valido)
    async with SessionLocal() as session:
        await aplicar_route_unassignable(
            session,
            RouteUnassignablePayload(
                ruta_id="r-1", shipment_id=envio.id, motivo="sin vehículo viable"
            ),
        )
    fila = await _outbox("shipment.delayed")

    assert set(fila.payload) == set(fixture["payload"])
    assert fila.payload["motivo"] == "sin vehículo viable"
    assert fila.payload["nueva_eta"] is None
