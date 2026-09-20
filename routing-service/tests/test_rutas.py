"""Pruebas de la lógica de negocio: asignación, recálculo y telemetría."""

from sqlalchemy import select

from app.database import SessionLocal
from app.dominio import EstadoRuta
from app.models import OutboxEvent, Parada, Ruta
from app.schemas import ShipmentCreatedPayload, TelemetryAggregatedPayload
from app.servicios import asignar_ruta, recalcular_ruta


def _payload(evento: dict) -> ShipmentCreatedPayload:
    return ShipmentCreatedPayload.model_validate(evento["payload"])


async def test_asignacion_feliz_publica_route_assigned(evento_shipment_created, cliente_fleet):
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        assert ruta.estado == EstadoRuta.ASIGNADA.value
        assert ruta.vehicle_id == "v-001"
        assert ruta.vehicle_plate == "SVK123"
        assert ruta.distancia_km > 0
        assert ruta.eta_actual is not None
        eventos = (await session.execute(select(OutboxEvent))).scalars().all()
        tipos = [e.event_type for e in eventos]
        assert tipos == ["route.assigned"]
        assert eventos[0].payload["shipment_id"] == "s-1001"
        assert eventos[0].payload["vehicle_id"] == "v-001"


async def test_asignacion_persiste_paradas_con_eta(evento_shipment_created):
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        paradas = (
            (await session.execute(select(Parada).where(Parada.ruta_id == ruta.id))).scalars().all()
        )
        assert len(paradas) == 2
        assert paradas[0].orden == 0
        assert paradas[0].direccion == "Montería"
        assert paradas[1].eta_llegada is not None


async def test_sin_vehiculos_publica_route_unassignable(evento_shipment_created, cliente_fleet):
    cliente_fleet._vehiculos = []
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        assert ruta.estado == EstadoRuta.NO_ASIGNABLE.value
        tipos = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
        assert tipos == ["route.unassignable"]


async def test_vehiculo_insuficiente_marca_no_asignable(evento_shipment_created, cliente_fleet):
    cliente_fleet._vehiculos[0].capacity_kg = 1000
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        assert ruta.estado == EstadoRuta.NO_ASIGNABLE.value
        assert "capacidad" in (ruta.motivo or "")


async def test_fleet_caido_deja_ruta_pendiente_sin_publicar(evento_shipment_created, cliente_fleet):
    from app.cliente_fleet import FleetNoDisponible

    cliente_fleet._error = FleetNoDisponible("fleet caído")
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        assert ruta.estado == EstadoRuta.PENDIENTE.value
        assert (await session.execute(select(OutboxEvent))).scalars().first() is None


async def test_recalculo_con_alternativa_cambia_vehiculo(evento_shipment_created, cliente_fleet):
    cliente_fleet._vehiculos.append(
        cliente_fleet._vehiculos[0].model_copy(update={"id": "v-002", "plate": "XYZ999"})
    )
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        ruta_id = ruta.id
    cliente_fleet._vehiculos = [v for v in cliente_fleet._vehiculos if v.id != "v-001"]
    async with SessionLocal() as session:
        ruta = await recalcular_ruta(
            session, ruta_id, causa="incidente", excluir_vehicle_id="v-001"
        )
        assert ruta.estado == EstadoRuta.RECALCULADA.value
        assert ruta.vehicle_id == "v-002"
        assert ruta.intentos_recalculo == 1
        tipos = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
        assert "route.recalculated" in tipos


async def test_recalculo_sin_alternativa_publica_unassignable(
    evento_shipment_created, cliente_fleet
):
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        ruta_id = ruta.id
    async with SessionLocal() as session:
        ruta = await recalcular_ruta(
            session, ruta_id, causa="incidente", excluir_vehicle_id="v-001"
        )
        assert ruta.estado == EstadoRuta.NO_ASIGNABLE.value
        tipos = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
        assert "route.unassignable" in tipos


async def test_recalculo_no_toca_ruta_no_asignable(evento_shipment_created, cliente_fleet):
    cliente_fleet._vehiculos = []
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        ruta_id = ruta.id
    cliente_fleet._vehiculos = []
    async with SessionLocal() as session:
        ruta = await recalcular_ruta(session, ruta_id, causa="incidente")
        assert ruta.estado == EstadoRuta.NO_ASIGNABLE.value


async def test_ventana_incumplible_marca_no_asignable(evento_shipment_created):
    from datetime import datetime, timezone

    from app.schemas import VentanaEntrega

    payload = _payload(evento_shipment_created)
    payload.ventana_entrega = VentanaEntrega(
        desde=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        hasta=datetime(2000, 1, 1, 18, 0, tzinfo=timezone.utc),  # hace tiempo que pasó
    )
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, payload)
        assert ruta.estado == EstadoRuta.NO_ASIGNABLE.value
        assert "ventana" in (ruta.motivo or "")


async def test_desvio_telemetria_publica_recalculated(
    evento_shipment_created, evento_telemetry_aggregated, cliente_fleet
):
    async with SessionLocal() as session:
        ruta = await asignar_ruta(session, _payload(evento_shipment_created))
        eta_antes = ruta.eta_actual.replace(tzinfo=None)  # aiosqlite devuelve naive
    telemetria = TelemetryAggregatedPayload.model_validate(evento_telemetry_aggregated["payload"])
    async with SessionLocal() as session:
        ruta = await session.get(Ruta, ruta.id)
        # Desvío simulado: ETA planificada mucho menor que la duración real.
        ruta.duracion_min = 600
        await session.commit()
        ruta = await session.get(Ruta, ruta.id)
        from app.servicios import actualizar_por_telemetria

        actualizada = await actualizar_por_telemetria(session, telemetria)
        assert actualizada is not None
        assert actualizada.tipo_calculo == "estimado"
        assert actualizada.eta_actual > eta_antes


async def test_desvio_pequeno_no_publica_nada(evento_shipment_created, evento_telemetry_aggregated):
    async with SessionLocal() as session:
        await asignar_ruta(session, _payload(evento_shipment_created))
    telemetria = TelemetryAggregatedPayload.model_validate(evento_telemetry_aggregated["payload"])
    telemetria.velocidad_promedio_kmh = 100
    telemetria.detenido = False
    async with SessionLocal() as session:
        from app.servicios import actualizar_por_telemetria

        assert await actualizar_por_telemetria(session, telemetria) is None
        tipos = [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]
        assert "route.recalculated" not in tipos
