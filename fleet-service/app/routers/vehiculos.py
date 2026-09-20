"""Endpoints de vehículos (ficha 3.2 del documento)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import servicios
from app.database import get_session
from app.schemas import (
    CambioEstado,
    PaginaVehiculos,
    VehiculoActualizar,
    VehiculoCrear,
    VehiculoDisponibleOut,
    VehiculoOut,
)

router = APIRouter(prefix="/api/v1/vehiculos", tags=["vehiculos"])


# OJO: esta ruta va ANTES de /{vehiculo_id}, si no "disponibles" se toma como id.
@router.get(
    "/disponibles",
    response_model=List[VehiculoDisponibleOut],
    summary="Vehículos que pueden aceptar una nueva carga",
)
async def vehiculos_disponibles(
    tipo: Optional[str] = Query(default=None, description="furgon, refrigerado, cisterna..."),
    zona: Optional[str] = Query(default=None, description="Zona geográfica actual"),
    capacidad_min_kg: Optional[float] = Query(default=None, ge=0),
    volumen_min_m3: Optional[float] = Query(default=None, ge=0),
    refrigerado: Optional[bool] = Query(default=None),
    hazmat: Optional[bool] = Query(default=None),
    limite: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Consulta síncrona que hace Routing Service antes de asignar una ruta."""
    return await servicios.buscar_disponibles(
        session,
        tipo=tipo,
        zona=zona,
        capacidad_min_kg=capacidad_min_kg,
        volumen_min_m3=volumen_min_m3,
        refrigerado=refrigerado,
        hazmat=hazmat,
        limite=limite,
    )


@router.get("", response_model=PaginaVehiculos, summary="Listado del catálogo")
async def listar(
    estado: Optional[str] = Query(default=None),
    zona: Optional[str] = Query(default=None),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    total, items = await servicios.listar_vehiculos(session, estado, zona, limite, desplazamiento)
    return PaginaVehiculos(total=total, items=[VehiculoOut.model_validate(v) for v in items])


@router.post(
    "", response_model=VehiculoOut, status_code=status.HTTP_201_CREATED, summary="Alta de vehículo"
)
async def crear(datos: VehiculoCrear, session: AsyncSession = Depends(get_session)):
    return await servicios.crear_vehiculo(session, datos)


@router.get("/{vehiculo_id}", response_model=VehiculoOut, summary="Ficha del vehículo")
async def obtener(vehiculo_id: str, session: AsyncSession = Depends(get_session)):
    return await servicios.obtener_vehiculo(session, vehiculo_id)


@router.patch("/{vehiculo_id}", response_model=VehiculoOut, summary="Actualizar ficha técnica")
async def actualizar(
    vehiculo_id: str, datos: VehiculoActualizar, session: AsyncSession = Depends(get_session)
):
    return await servicios.actualizar_vehiculo(session, vehiculo_id, datos)


@router.patch(
    "/{vehiculo_id}/estado",
    response_model=VehiculoOut,
    summary="Cambiar el estado operativo",
    description=(
        "Valida la transición contra la máquina de estados y publica "
        "`vehicle.status_changed` mediante el patrón Outbox."
    ),
)
async def cambiar_estado(
    vehiculo_id: str, datos: CambioEstado, session: AsyncSession = Depends(get_session)
):
    vehiculo = await servicios.obtener_vehiculo(session, vehiculo_id)
    vehiculo, _ = await servicios.cambiar_estado(
        session, vehiculo, datos.estado, motivo=datos.motivo, origen="api"
    )
    return vehiculo
