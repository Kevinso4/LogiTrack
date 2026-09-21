"""API HTTP del Shipment Service.

El tipo rico (crear/envíos) lo usan el equipo de operaciones y el perímetro; el
tipo delgado (`seguimiento`) es lo único que ve el cliente: no filtra quién
conduce ni internals.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.errores import RecursoNoEncontrado
from app.models import Envio, HistorialEnvio
from app.schemas import (
    DevolucionRequest,
    EnvioOut,
    EnvioRequest,
    HistorialOut,
    IncidenteRequest,
    PruebaEntregaRequest,
    SeguimientoOut,
)
from app.servicios import crear_envio, devolver, entregar, incidente, listar_envios

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["envios"])


@router.post(
    "/envios",
    response_model=EnvioOut,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un envío y publica shipment.created (inicio de la saga)",
)
async def crear(solicitud: EnvioRequest, session: AsyncSession = Depends(get_session)) -> Envio:
    return await crear_envio(session, solicitud)


@router.get("/envios", response_model=list[EnvioOut], summary="Lista envíos (filtro por estado)")
async def listar(
    estado: str | None = Query(default=None),
    limite: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Envio]:
    return await listar_envios(session, estado, limite, offset)


@router.get("/envios/{shipment_id}", response_model=EnvioOut, summary="Consulta un envío")
async def obtener(shipment_id: str, session: AsyncSession = Depends(get_session)) -> Envio:
    envio = await session.get(Envio, shipment_id)
    if envio is None:
        raise RecursoNoEncontrado(f"No existe el envío {shipment_id}")
    return envio


@router.get(
    "/envios/{shipment_id}/seguimiento",
    response_model=SeguimientoOut,
    summary="Tipo delgado para el cliente: ¿dónde va la carga?",
)
async def seguimiento(
    shipment_id: str, session: AsyncSession = Depends(get_session)
) -> SeguimientoOut:
    envio = await session.get(Envio, shipment_id)
    if envio is None:
        raise RecursoNoEncontrado(f"No existe el envío {shipment_id}")
    return SeguimientoOut(
        shipment_id=envio.id,
        estado=envio.estado,
        eta=envio.eta,
        ultima_actualizacion=envio.actualizado_en,
        motivo=envio.motivo,
    )


@router.get(
    "/envios/{shipment_id}/historial",
    response_model=list[HistorialOut],
    summary="Auditoría de transiciones del envío",
)
async def historial(
    shipment_id: str, session: AsyncSession = Depends(get_session)
) -> list[HistorialEnvio]:
    return (
        (
            await session.execute(
                select(HistorialEnvio)
                .where(HistorialEnvio.shipment_id == shipment_id)
                .order_by(HistorialEnvio.id)
            )
        )
        .scalars()
        .all()
    )


@router.post(
    "/envios/{shipment_id}/incidente",
    response_model=EnvioOut,
    summary="Reporta un incidente; confirma -> shipment.incident (saga)",
)
async def reportar_incidente(
    shipment_id: str,
    cuerpo: IncidenteRequest,
    session: AsyncSession = Depends(get_session),
) -> Envio:
    return await incidente(
        session,
        shipment_id,
        tipo=cuerpo.tipo,
        confirmado=cuerpo.confirmado,
        motivo=cuerpo.motivo,
    )


@router.post(
    "/envios/{shipment_id}/entregar",
    response_model=EnvioOut,
    summary="Entrega con prueba (POD) y publica shipment.delivered",
)
async def entregar_envio(
    shipment_id: str,
    cuerpo: PruebaEntregaRequest,
    session: AsyncSession = Depends(get_session),
) -> Envio:
    return await entregar(session, shipment_id, cuerpo)


@router.post(
    "/envios/{shipment_id}/devolver",
    response_model=EnvioOut,
    summary="Devolución y publica shipment.returned",
)
async def devolver_envio(
    shipment_id: str,
    cuerpo: DevolucionRequest,
    session: AsyncSession = Depends(get_session),
) -> Envio:
    return await devolver(session, shipment_id, motivo=cuerpo.motivo)
