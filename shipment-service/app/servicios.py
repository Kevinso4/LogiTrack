"""Lógica de negocio del Shipment Service (SRP, sección 5e).

Una sola razón de cambio: cómo evoluciona el ciclo de vida del envío. Cada
evento de Routing/Customs es un "policía" que pide una transición; la máquina
de estados (`app.dominio.transicion_valida`) decide si se concede.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dominio import EstadoEnvio, ESTADOS_FINALES, transicion_valida
from app.errores import ConflictoRecurso, RecursoNoEncontrado, ReglaNegocioViolada
from app.events.outbox import registrar_evento
from app.models import Envio, HistorialEnvio, PruebaEntrega
from app.observabilidad import envios_creados, envios_transicionados, log
from app.schemas import (
    CustomsClearedPayload,
    CustomsHeldPayload,
    EnvioRequest,
    PruebaEntregaRequest,
    RouteAssignedPayload,
    RouteRecalculatedPayload,
    RouteUnassignablePayload,
)

logger = logging.getLogger(__name__)

EVENTO_CREADO = "shipment.created"
EVENTO_DELIVERED = "shipment.delivered"
EVENTO_INCIDENTE = "shipment.incident"
EVENTO_RETORNADO = "shipment.returned"
EVENTO_RETRASADO = "shipment.delayed"

# Tipos de incidencia que implican avería del vehículo (contrato que consume
# Fleet). La misma lista vive en Fleet; aquí solo se valida al publicar.
TIPOS_INCIDENCIA_VEHICULO = {"averia", "accidente", "vehicle_breakdown", "panne"}


def _payload_creado(envio: Envio) -> Dict:
    return {
        "shipment_id": envio.id,
        "client_id": envio.client_id,
        "origen": envio.origen,
        "destino": envio.destino,
        "peso_kg": envio.peso_kg,
        "volumen_m3": envio.volumen_m3,
        "is_international": envio.is_international,
        "sla_deadline": envio.sla_deadline.isoformat() if envio.sla_deadline else None,
        "requiere_refrigeracion": envio.requiere_refrigeracion,
        "requiere_hazmat": envio.requiere_hazmat,
        "ventana_entrega": envio.ventana_entrega,
    }


async def _transicionar(
    session: AsyncSession,
    envio: Envio,
    hasta: EstadoEnvio,
    motivo: Optional[str],
    evento_type: Optional[str] = None,
    evento_payload: Optional[Dict] = None,
    hacer_commit: bool = True,
) -> Envio:
    desde = EstadoEnvio(envio.estado)
    if not transicion_valida(desde, hasta):
        raise ReglaNegocioViolada(f"Transición no permitida: {desde.value} -> {hasta.value}")
    envio.estado = hasta.value
    envio.motivo = motivo
    session.add(
        HistorialEnvio(
            shipment_id=envio.id,
            desde=desde.value,
            hasta=hasta.value,
            motivo=motivo,
        )
    )
    envios_transicionados.labels(desde.value, hasta.value).inc()
    if evento_type is not None:
        registrar_evento(session, evento_type, evento_payload or {})
    log(
        logger,
        logging.INFO,
        "envio.transicion",
        shipment_id=envio.id,
        desde=desde.value,
        hasta=hasta.value,
    )
    if hacer_commit:
        await session.commit()
    return envio


async def _obtener_envio(session: AsyncSession, shipment_id: str) -> Envio:
    envio = await session.get(Envio, shipment_id)
    if envio is None:
        raise RecursoNoEncontrado(f"No existe el envío {shipment_id}")
    return envio


async def _obtener_envio_por_ruta(session: AsyncSession, shipment_id: str) -> Optional[Envio]:
    return await session.get(Envio, shipment_id)


# --------------------------------------------------------------------------
# Creación.
# --------------------------------------------------------------------------
async def crear_envio(
    session: AsyncSession, request: EnvioRequest, hacer_commit: bool = True
) -> Envio:
    envio = Envio(
        client_id=request.client_id,
        origen=request.origen.model_dump(mode="json"),
        destino=request.destino.model_dump(mode="json"),
        peso_kg=request.peso_kg,
        volumen_m3=request.volumen_m3,
        is_international=request.is_international,
        sla_deadline=request.sla_deadline,
        requiere_refrigeracion=request.requiere_refrigeracion,
        requiere_hazmat=request.requiere_hazmat,
        ventana_entrega=(
            request.ventana_entrega.model_dump(mode="json") if request.ventana_entrega else None
        ),
        estado=EstadoEnvio.EN_ALMACEN.value,
    )
    session.add(envio)
    await session.flush()
    # Huella inicial del ciclo de vida y el evento de salida viajan en el
    # mismo commit: patrón Outbox.
    session.add(HistorialEnvio(shipment_id=envio.id, desde=None, hasta=envio.estado))
    registrar_evento(session, EVENTO_CREADO, _payload_creado(envio))
    envios_creados.labels(str(envio.is_international)).inc()
    log(logger, logging.INFO, "envio.creado", shipment_id=envio.id)
    if hacer_commit:
        await session.commit()
    return envio


# --------------------------------------------------------------------------
# Eventos de Routing.
# --------------------------------------------------------------------------
async def aplicar_route_assigned(
    session: AsyncSession, payload: RouteAssignedPayload, hacer_commit: bool = True
) -> Envio:
    envio = await _obtener_envio(session, payload.shipment_id)
    # El reenvío del mismo route.assigned no vuelve a mutar el estado si ya
    # está en ruta; la idempotencia global la da processed_events de todos
    # modos, pero esta guardia evita tocar el historial por duplicado.
    if envio.estado == EstadoEnvio.EN_RUTA.value and envio.ruta_id == payload.ruta_id:
        return envio
    envio.ruta_id = payload.ruta_id
    envio.vehicle_id = payload.vehicle_id
    envio.vehicle_plate = payload.vehicle_plate
    envio.eta = payload.eta
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.EN_RUTA,
        motivo="ruta asignada",
        evento_type=None,
        hacer_commit=hacer_commit,
    )


async def aplicar_route_recalculated(
    session: AsyncSession, payload: RouteRecalculatedPayload, hacer_commit: bool = True
) -> Envio:
    envio = await _obtener_envio(session, payload.shipment_id)
    if EstadoEnvio(envio.estado) in ESTADOS_FINALES:
        raise ReglaNegocioViolada(f"El envío ya está {envio.estado}; no se recalcula")
    envio.ruta_id = payload.ruta_id
    envio.vehicle_id = payload.vehicle_id
    envio.vehicle_plate = payload.vehicle_plate
    envio.eta = payload.eta
    envio.motivo = payload.motivo or "ruta recalculada"
    if envio.estado not in (EstadoEnvio.EN_RUTA.value, EstadoEnvio.RETRASADO.value):
        envio = await _transicionar(
            session,
            envio,
            EstadoEnvio.EN_RUTA,
            motivo=payload.motivo or "ruta recalculada",
            hacer_commit=False,
        )
    if hacer_commit:
        await session.commit()
    return envio


async def aplicar_route_unassignable(
    session: AsyncSession, payload: RouteUnassignablePayload, hacer_commit: bool = True
) -> Envio:
    envio = await _obtener_envio(session, payload.shipment_id)
    if envio.estado == EstadoEnvio.RETRASADO.value:
        return envio  # ya quedó retrasado por este motivo
    motivo = payload.motivo or "sin vehículo viable"
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.RETRASADO,
        motivo=motivo,
        evento_type=EVENTO_RETRASADO,
        evento_payload={
            "shipment_id": envio.id,
            "motivo": motivo,
            "nueva_eta": None,
        },
        hacer_commit=hacer_commit,
    )


# --------------------------------------------------------------------------
# Eventos de Customs (desvío deliberado de la matriz, ver README raíz).
# --------------------------------------------------------------------------
async def aplicar_customs_held(
    session: AsyncSession, payload: CustomsHeldPayload, hacer_commit: bool = True
) -> Envio:
    envio = await _obtener_envio(session, payload.shipment_id)
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.RETENIDO_ADUANERA,
        motivo=payload.motivo or "retención en aduana",
        hacer_commit=hacer_commit,
    )


async def aplicar_customs_cleared(
    session: AsyncSession, payload: CustomsClearedPayload, hacer_commit: bool = True
) -> Envio:
    envio = await _obtener_envio(session, payload.shipment_id)
    if envio.estado != EstadoEnvio.RETENIDO_ADUANERA.value:
        raise ConflictoRecurso(f"El envío NO está retenido en aduana (estado: {envio.estado})")
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.EN_RUTA,
        motivo=payload.motivo or "desaduanado",
        hacer_commit=hacer_commit,
    )


# --------------------------------------------------------------------------
# Operaciones vía REST (operaciones, conductor).
# --------------------------------------------------------------------------
async def incidente(
    session: AsyncSession,
    shipment_id: str,
    tipo: str,
    confirmado: bool = True,
    motivo: Optional[str] = None,
    hacer_commit: bool = True,
) -> Envio:
    envio = await _obtener_envio(session, shipment_id)
    if tipo.lower() in TIPOS_INCIDENCIA_VEHICULO and not confirmado:
        log(
            logger,
            logging.INFO,
            "incidente.no_confirmado.ignorado",
            shipment_id=envio.id,
            tipo=tipo,
        )
        if hacer_commit:
            await session.commit()
        return envio
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.INCIDENTE,
        motivo=motivo or f"incidencia reportada: {tipo}",
        evento_type=EVENTO_INCIDENTE,
        evento_payload={
            # Contrato del Fleet Service (vehiculo.status_changed):
            "vehicle_id": envio.vehicle_id,
            "shipment_id": envio.id,
            "tipo": tipo,
            "confirmado": confirmado,
            "motivo": motivo,
        },
        hacer_commit=hacer_commit,
    )


async def entregar(
    session: AsyncSession,
    shipment_id: str,
    prueba: PruebaEntregaRequest,
    hacer_commit: bool = True,
) -> Envio:
    envio = await _obtener_envio(session, shipment_id)
    if EstadoEnvio(envio.estado) in ESTADOS_FINALES:
        raise ConflictoRecurso(f"El envío ya está {envio.estado}")

    prueba_registro = PruebaEntrega(
        shipment_id=envio.id,
        nombre_recibe=prueba.nombre_recibe,
        documento_recibe=prueba.documento_recibe,
        firma_foto_url=prueba.firma_foto_url,
        comentario=prueba.comentario,
    )
    session.add(prueba_registro)
    momento = datetime.now(timezone.utc)
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.ENTREGADO,
        motivo="entregado al destinatario",
        evento_type=EVENTO_DELIVERED,
        evento_payload={
            "shipment_id": envio.id,
            "entregado_en": momento.isoformat(),
            "vehicle_id": envio.vehicle_id,
            "vehicle_plate": envio.vehicle_plate,
            "destinatario": prueba.nombre_recibe,
        },
        hacer_commit=hacer_commit,
    )


async def devolver(
    session: AsyncSession,
    shipment_id: str,
    motivo: Optional[str] = None,
    hacer_commit: bool = True,
) -> Envio:
    envio = await _obtener_envio(session, shipment_id)
    if EstadoEnvio(envio.estado) in ESTADOS_FINALES:
        raise ConflictoRecurso(f"El envío ya está {envio.estado}")
    motivo_real = motivo or "devolución al origen"
    return await _transicionar(
        session,
        envio,
        EstadoEnvio.RETORNADO,
        motivo=motivo_real,
        evento_type=EVENTO_RETORNADO,
        evento_payload={"shipment_id": envio.id, "motivo": motivo_real},
        hacer_commit=hacer_commit,
    )


async def listar_envios(
    session: AsyncSession, estado: Optional[str], limite: int, offset: int
) -> List[Envio]:
    consulta = select(Envio).order_by(Envio.creado_en.desc()).limit(limite).offset(offset)
    if estado:
        consulta = consulta.where(Envio.estado == estado)
    return (await session.execute(consulta)).scalars().all()
