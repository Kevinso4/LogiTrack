"""Endpoints de conductores (ficha 3.2 del documento)."""

from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import servicios
from app.database import get_session
from app.schemas import (
    AsignarVehiculo,
    ConductorCrear,
    ConductorOut,
    DisponibilidadConductor,
    RegistrarHoras,
)

router = APIRouter(prefix="/api/v1/conductores", tags=["conductores"])


@router.post("", response_model=ConductorOut, status_code=status.HTTP_201_CREATED)
async def crear(datos: ConductorCrear, session: AsyncSession = Depends(get_session)):
    return await servicios.crear_conductor(session, datos)


@router.get("", response_model=List[ConductorOut])
async def listar(session: AsyncSession = Depends(get_session)):
    return await servicios.listar_conductores(session)


@router.get("/{conductor_id}", response_model=ConductorOut)
async def obtener(conductor_id: str, session: AsyncSession = Depends(get_session)):
    return await servicios.obtener_conductor(session, conductor_id)


@router.get(
    "/{conductor_id}/disponibilidad",
    response_model=DisponibilidadConductor,
    summary="¿Puede este conductor tomar una ruta ahora?",
    description="Licencia vigente + tope semanal de conducción (descanso obligatorio).",
)
async def disponibilidad(conductor_id: str, session: AsyncSession = Depends(get_session)):
    return await servicios.calcular_disponibilidad(session, conductor_id)


@router.put("/{conductor_id}/vehiculo", response_model=ConductorOut)
async def asignar_vehiculo(
    conductor_id: str, datos: AsignarVehiculo, session: AsyncSession = Depends(get_session)
):
    return await servicios.asignar_vehiculo(session, conductor_id, datos.vehicle_id)


@router.post("/{conductor_id}/horas", response_model=ConductorOut)
async def registrar_horas(
    conductor_id: str, datos: RegistrarHoras, session: AsyncSession = Depends(get_session)
):
    return await servicios.registrar_horas(session, conductor_id, datos.horas)
