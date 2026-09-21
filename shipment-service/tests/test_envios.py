"""Pruebas de la lógica de negocio: ciclo de vida y máquina de estados."""

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.dominio import EstadoEnvio
from app.errores import ConflictoRecurso, ReglaNegocioViolada
from app.models import Envio, HistorialEnvio, OutboxEvent, PruebaEntrega
from app.schemas import (
    CustomsClearedPayload,
    CustomsHeldPayload,
    EnvioRequest,
    PruebaEntregaRequest,
    RouteAssignedPayload,
    RouteUnassignablePayload,
)
from app.servicios import (
    _payload_creado,
    _transicionar,
    aplicar_customs_cleared,
    aplicar_customs_held,
    aplicar_route_assigned,
    aplicar_route_unassignable,
    crear_envio,
    devolver,
    entregar,
    incidente,
)


def _solicitud(envio_valido) -> EnvioRequest:
    return EnvioRequest.model_validate(envio_valido)


async def _crear(envio_valido) -> Envio:
    async with SessionLocal() as session:
        return await crear_envio(session, _solicitud(envio_valido))


async def _tipos_eventos(session) -> list:
    return [e.event_type for e in (await session.execute(select(OutboxEvent))).scalars().all()]


async def test_crear_envio_publica_shipment_created_con_contrato_completo(envio_valido):
    async with SessionLocal() as session:
        envio = await crear_envio(session, _solicitud(envio_valido))
        assert envio.estado == EstadoEnvio.EN_ALMACEN.value
        payload = _payload_creado(envio)
        assert payload["shipment_id"] == envio.id
        assert payload["origen"]["lat"] == 8.75
        assert payload["destino"]["lon"] == -74.77
        assert payload["peso_kg"] == 8000
        assert payload["ventana_entrega"]["desde"] is not None
        assert "route.assigned" not in await _tipos_eventos(session)


async def test_crear_envio_registra_historial_inicial(envio_valido):
    await _crear(envio_valido)
    async with SessionLocal() as session:
        registro = (await session.execute(select(HistorialEnvio))).scalars().first()
        assert registro is not None
        assert registro.hasta == EstadoEnvio.EN_ALMACEN.value


async def test_route_assigned_pone_el_envio_en_ruta(envio_valido, evento_route_assigned, cliente):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        envio = await aplicar_route_assigned(session, payload)
        assert envio.estado == EstadoEnvio.EN_RUTA.value
        assert envio.vehicle_id == "v-001"
        assert envio.ruta_id == "r-900"
        assert envio.eta is not None
        # tras route.assigned NO se publica ningún evento de salida


async def test_transicion_invalida_desde_entregado_rebotado(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await entregar(
            session,
            envio.id,
            PruebaEntregaRequest(nombre_recibe="Ana Ruiz"),
            hacer_commit=False,
        )
        await session.commit()
    async with SessionLocal() as session:
        with pytest.raises(ReglaNegocioViolada):
            await aplicar_route_assigned(session, payload)


async def test_route_unassignable_retrasa_y_publica_delayed(envio_valido):
    envio = await _crear(envio_valido)
    payload = RouteUnassignablePayload(
        ruta_id="r-900", shipment_id=envio.id, motivo="sin vehículo viable"
    )
    async with SessionLocal() as session:
        envio = await aplicar_route_unassignable(session, payload)
        assert envio.estado == EstadoEnvio.RETRASADO.value
        tipos = await _tipos_eventos(session)
        assert "shipment.delayed" in tipos
        delayed = (
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.event_type == "shipment.delayed")
                )
            )
            .scalars()
            .first()
        )
        assert delayed.payload["shipment_id"] == envio.id


async def test_reentrega_unassignable_no_duplica_el_retraso(envio_valido):
    envio = await _crear(envio_valido)
    payload = RouteUnassignablePayload(
        ruta_id="r-900", shipment_id=envio.id, motivo="sin vehículo viable"
    )
    async with SessionLocal() as session:
        await aplicar_route_unassignable(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await aplicar_route_unassignable(session, payload)
        envio = await session.get(Envio, envio.id)
        assert envio.estado == EstadoEnvio.RETRASADO.value
        tipos = await _tipos_eventos(session)
        assert tipos.count("shipment.delayed") == 1


async def test_customs_held_y_cleared_retiene_y_libera(envio_internacional):
    envio = await _crear(envio_internacional)
    async with SessionLocal() as session:
        envio = await aplicar_customs_held(
            session,
            CustomsHeldPayload(shipment_id=envio.id, motivo="documentación incompleta"),
        )
        assert envio.estado == EstadoEnvio.RETENIDO_ADUANERA.value
        envio = await aplicar_customs_cleared(
            session, CustomsClearedPayload(shipment_id=envio.id, motivo="documentos ok")
        )
        assert envio.estado == EstadoEnvio.EN_RUTA.value


async def test_customs_cleared_sin_retencion_previa_rebota(envio_valido):
    envio = await _crear(envio_valido)
    async with SessionLocal() as session:
        with pytest.raises(ConflictoRecurso):
            await aplicar_customs_cleared(session, CustomsClearedPayload(shipment_id=envio.id))


async def test_incidente_confirmado_publica_shipment_incident_para_fleet(
    envio_valido, evento_route_assigned
):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        envio = await incidente(
            session,
            envio.id,
            tipo="averia",
            confirmado=True,
            motivo="tren de aterrizaje",
        )
        assert envio.estado == EstadoEnvio.INCIDENTE.value
        incident = (
            (
                await session.execute(
                    select(OutboxEvent).where(OutboxEvent.event_type == "shipment.incident")
                )
            )
            .scalars()
            .first()
        )
        assert incident.payload["vehicle_id"] == "v-001"
        assert incident.payload["shipment_id"] == envio.id
        assert incident.payload["tipo"] == "averia"
        assert incident.payload["confirmado"] is True


async def test_incidente_no_confirmado_no_cambia_estado(envio_valido):
    envio = await _crear(envio_valido)
    async with SessionLocal() as session:
        envio = await incidente(
            session, envio.id, tipo="averia", confirmado=False, motivo="falso positivo"
        )
        assert envio.estado == EstadoEnvio.EN_ALMACEN.value
        tipos = await _tipos_eventos(session)
        assert "shipment.incident" not in tipos


async def test_entregar_guarda_pod_y_publica_delivered(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        envio = await entregar(
            session,
            envio.id,
            PruebaEntregaRequest(
                nombre_recibe="Ana Ruiz",
                documento_recibe="CC-123456",
                comentario="deja con vecino",
            ),
        )
        assert envio.estado == EstadoEnvio.ENTREGADO.value
        pod = (
            (
                await session.execute(
                    select(PruebaEntrega).where(PruebaEntrega.shipment_id == envio.id)
                )
            )
            .scalars()
            .first()
        )
        assert pod.nombre_recibe == "Ana Ruiz"
        tipos = await _tipos_eventos(session)
        assert "shipment.delivered" in tipos


async def test_no_se_puede_entregar_dos_veces(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await entregar(
            session,
            envio.id,
            PruebaEntregaRequest(nombre_recibe="Ana"),
            hacer_commit=False,
        )
        await session.commit()
    async with SessionLocal() as session:
        with pytest.raises(ConflictoRecurso):
            await entregar(session, envio.id, PruebaEntregaRequest(nombre_recibe="Luis"))


async def test_devolver_publica_returned(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        envio = await devolver(session, envio.id, motivo="destinatario ausente")
        assert envio.estado == EstadoEnvio.RETORNADO.value
        tipos = await _tipos_eventos(session)
        assert "shipment.returned" in tipos


async def test_no_se_puede_devolver_un_retornado(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    payload.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, payload, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await devolver(session, envio.id, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        with pytest.raises(ConflictoRecurso):
            await devolver(session, envio.id)


async def test_retrasado_a_incidente_prohibido(envio_valido):
    envio = await _crear(envio_valido)
    payload = RouteUnassignablePayload(
        ruta_id="r-900", shipment_id=envio.id, motivo="sin vehículo viable"
    )
    async with SessionLocal() as session:
        await aplicar_route_unassignable(session, payload)
    async with SessionLocal() as session:
        with pytest.raises(ReglaNegocioViolada):
            await incidente(session, envio.id, tipo="averia", confirmado=True)


async def test_retrasado_no_publica_incidente(envio_valido):
    envio = await _crear(envio_valido)
    payload = RouteUnassignablePayload(
        ruta_id="r-900", shipment_id=envio.id, motivo="sin vehículo viable"
    )
    async with SessionLocal() as session:
        await aplicar_route_unassignable(session, payload)
        with pytest.raises(ReglaNegocioViolada):
            await incidente(session, envio.id, tipo="averia", confirmado=True)
        tipos = await _tipos_eventos(session)
        assert "shipment.incident" not in tipos


async def test_retrasado_a_en_ruta_via_evento_permitido(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    payload = RouteUnassignablePayload(
        ruta_id="r-900", shipment_id=envio.id, motivo="sin vehículo viable"
    )
    async with SessionLocal() as session:
        await aplicar_route_unassignable(session, payload)
    asignada = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    asignada.shipment_id = envio.id
    async with SessionLocal() as session:
        envio = await aplicar_route_assigned(session, asignada)
        assert envio.estado == EstadoEnvio.EN_RUTA.value
        assert envio.ruta_id == asignada.ruta_id


async def test_entrar_en_ruta_desde_api_prohibido(envio_valido):
    envio = await _crear(envio_valido)
    async with SessionLocal() as session:
        with pytest.raises(ReglaNegocioViolada):
            await _transicionar(session, envio, EstadoEnvio.EN_RUTA, motivo="intento desde API")
        await session.rollback()


async def test_entregado_no_sale_por_incidente_ni_devolucion(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    asignada = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    asignada.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, asignada, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await entregar(
            session, envio.id, PruebaEntregaRequest(nombre_recibe="Ana"), hacer_commit=False
        )
        await session.commit()
    async with SessionLocal() as session:
        with pytest.raises(ReglaNegocioViolada):
            await incidente(session, envio.id, tipo="averia", confirmado=True)
    async with SessionLocal() as session:
        with pytest.raises(ConflictoRecurso):
            await devolver(session, envio.id)


async def test_retornado_no_sale_por_incidente_ni_entrega(envio_valido, evento_route_assigned):
    envio = await _crear(envio_valido)
    asignada = RouteAssignedPayload.model_validate(evento_route_assigned["payload"])
    asignada.shipment_id = envio.id
    async with SessionLocal() as session:
        await aplicar_route_assigned(session, asignada, hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        await devolver(session, envio.id, motivo="destinatario ausente", hacer_commit=False)
        await session.commit()
    async with SessionLocal() as session:
        with pytest.raises(ReglaNegocioViolada):
            await incidente(session, envio.id, tipo="averia", confirmado=True)
    async with SessionLocal() as session:
        with pytest.raises(ConflictoRecurso):
            await entregar(session, envio.id, PruebaEntregaRequest(nombre_recibe="Ana"))
