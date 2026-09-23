"""API HTTP del Routing Service (tipos delgado y rico, sección 5e).

REST expone solo lo que el cliente necesita: las consultas de ruta (tipo
delgado) y los resultados de la optimización (tipo rico). El cálculo vive en
`app.servicios`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.dominio import EstadoRuta
from app.errores import RecursoNoEncontrado
from app.models import Parada, Ruta
from app.schemas import NavegacionOut, ParadaOut, RecalcularRequest, RutaOut
from app.servicios import cache_eta, recalcular_ruta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["rutas"])


async def _obtener_ruta(session: AsyncSession, ruta_id: str) -> Ruta:
    ruta = await session.get(Ruta, ruta_id)
    if ruta is None:
        raise RecursoNoEncontrado(f"No existe la ruta {ruta_id}")
    return ruta


@router.get("/rutas/{ruta_id}", response_model=RutaOut, summary="Consulta una ruta")
async def obtener_ruta(ruta_id: str, session: AsyncSession = Depends(get_session)) -> Ruta:
    return await _obtener_ruta(session, ruta_id)


@router.get(
    "/rutas/shipment/{shipment_id}",
    response_model=RutaOut,
    summary="Ruta asociada a un envío",
)
async def ruta_por_shipment(shipment_id: str, session: AsyncSession = Depends(get_session)) -> Ruta:
    ruta = await session.scalar(select(Ruta).where(Ruta.shipment_id == shipment_id))
    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe ruta para el envío {shipment_id}",
        )
    return ruta


@router.post(
    "/rutas/{ruta_id}/recalcular",
    response_model=RutaOut,
    summary="Forzar recálculo (operación, advertencia o carga de alto valor)",
)
async def recalcular(
    ruta_id: str,
    cuerpo: RecalcularRequest = RecalcularRequest(),
    session: AsyncSession = Depends(get_session),
) -> Ruta:
    try:
        ruta = await recalcular_ruta(session, str(ruta_id), causa=cuerpo.causa)
    except RecursoNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ruta


@router.get(
    "/drivers/navegacion/{shipment_id}",
    response_model=NavegacionOut,
    summary="Contrato de la app del conductor (tipo delgado ISP)",
)
async def navegacion(
    shipment_id: str, session: AsyncSession = Depends(get_session)
) -> NavegacionOut:
    ruta = await session.scalar(select(Ruta).where(Ruta.shipment_id == shipment_id))
    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No existe ruta para el envío {shipment_id}",
        )
    if ruta.estado == EstadoRuta.NO_ASIGNABLE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La ruta no es navegable: {ruta.motivo}",
        )

    paradas = (
        (
            await session.execute(
                select(Parada).where(Parada.ruta_id == ruta.id).order_by(Parada.orden)
            )
        )
        .scalars()
        .all()
    )
    paradas_out = [
        ParadaOut(
            orden=p.orden,
            direccion=p.direccion,
            lat=p.lat,
            lng=p.lng,
            ventana_desde=p.ventana_desde,
            ventana_hasta=p.ventana_hasta,
            eta_llegada=p.eta_llegada,
        )
        for p in paradas
    ]
    eta = ruta.eta_actual
    tipo = ruta.tipo_calculo
    if ruta.estado in (EstadoRuta.ASIGNADA.value, EstadoRuta.RECALCULADA.value):
        desde_cache = await cache_eta().obtener(ruta.id)
        if desde_cache is not None:
            eta = desde_cache
            tipo = "estimado" if ruta.tipo_calculo == "estimado" else tipo
    return NavegacionOut(
        ruta_id=ruta.id,
        shipment_id=ruta.shipment_id,
        vehicle_id=ruta.vehicle_id,
        plate=ruta.vehicle_plate,
        eta=eta,
        distancia_km=ruta.distancia_km,
        tipo_calculo=tipo,
        paradas=paradas_out,
    )


@router.post("/rutas/estado", status_code=status.HTTP_200_OK, include_in_schema=False)
async def estado_rutas(session: AsyncSession = Depends(get_session)) -> dict:
    """Health de negocio: cuenta de rutas por estado (operación / tableros)."""
    filas = (await session.execute(select(Ruta.estado))).scalars().all()
    por_estado = {e.value: 0 for e in EstadoRuta}
    for e in filas:
        # .get y no += directo: la columna es String(30) y puede traer un
        # estado fuera del enum (dato legado, semilla vieja); sin esto el
        # health de negocio revienta con KeyError -> 500 (defecto 4.1).
        por_estado[e] = por_estado.get(e, 0) + 1
    return {"servicio": "routing-service", "rutas_por_estado": por_estado}
