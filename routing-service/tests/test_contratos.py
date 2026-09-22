"""Contratos publicados por Routing contra los fixtures de CONTRATOS.md.

Dos capas de verificación:

1. El sobré del fixture parsea con `EventoDominio` y su conjunto de claves es
   EXACTAMENTE el del sobre publicado.
2. El camino real de producción (consumir `shipment.created` →
   `asignar_ruta` → outbox) escribe un payload cuyo conjunto de claves
   coincide con el fixture: si mañana alguien renombra un campo, este test
   llora en el CI.
"""

import json
import pathlib

from sqlalchemy import select

from app.database import SessionLocal
from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.models import OutboxEvent

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
SOBRE_PROPIO = {"event_id", "event_type", "occurred_at", "producer", "trace_id", "payload"}


def _leer_fixture(nombre: str) -> dict:
    with open(FIXTURES / nombre, encoding="utf-8") as fh:
        return json.load(fh)


def test_sobre_route_assigned_es_valido_y_exacto():
    fixture = _leer_fixture("route.assigned.json")
    evento = EventoDominio.desde_bytes(json.dumps(fixture).encode("utf-8"))
    assert set(evento.model_dump(mode="json")) == SOBRE_PROPIO
    assert evento.event_type == "route.assigned"


def test_fixtures_de_tipo_ruta_parsean():
    for nombre in ("route.assigned.json", "route.recalculated.json", "route.unassignable.json"):
        fixture = _leer_fixture(nombre)
        evento = EventoDominio.desde_bytes(json.dumps(fixture).encode("utf-8"))
        assert set(evento.model_dump(mode="json")) == SOBRE_PROPIO


async def test_produccion_route_assigned_coincide_con_el_fixture(evento_shipment_created):
    fixture = _leer_fixture("route.assigned.json")
    await manejar_evento(
        EventoDominio(
            event_id="evt-contrato",
            event_type="shipment.created",
            payload=evento_shipment_created["payload"],
        )
    )
    async with SessionLocal() as session:
        fila = await session.scalar(select(OutboxEvent))

    assert fila.event_type == "route.assigned"
    assert set(fila.payload) == set(fixture["payload"])
    # Tipos del contrato: los fijos del fixture se conservan.
    assert isinstance(fila.payload["vehicle_id"], str)
    assert isinstance(fila.payload["distancia_km"], (int, float))
    assert isinstance(fila.payload["duracion_min"], (int, float))
    assert fila.payload["tipo_calculo"] in {"calculado", "estimado"}
    assert fila.payload["shipment_id"] == "s-1001"


def test_fixture_payload_route_unassignable_tiene_causa_y_motivo():
    payload = _leer_fixture("route.unassignable.json")["payload"]
    assert set(payload) == {"ruta_id", "shipment_id", "motivo", "causa"}
