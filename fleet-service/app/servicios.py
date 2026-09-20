"""Lógica de negocio del Fleet Service.

Única razón de cambio: cómo se administra la flota. Ni rutas, ni envíos, ni
facturación (SRP, sección 1.4).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dominio import ESTADOS_ASIGNABLES, EstadoVehiculo, TransicionInvalida, validar_transicion
from app.errores import ConflictoRecurso, RecursoNoEncontrado, ReglaNegocioViolada
from app.events.outbox import registrar_evento
from app.models import Driver, Vehicle
from app.observabilidad import cambios_estado, log
from app.schemas import ConductorCrear, DisponibilidadConductor, VehiculoActualizar, VehiculoCrear

logger = logging.getLogger(__name__)

EVENTO_ESTADO = "vehicle.status_changed"


# --------------------------------------------------------------------------
# Vehículos
# --------------------------------------------------------------------------
async def crear_vehiculo(session: AsyncSession, datos: VehiculoCrear) -> Vehicle:
    existente = await session.scalar(select(Vehicle).where(Vehicle.plate == datos.plate))
    if existente:
        raise ConflictoRecurso(
            f"Ya existe un vehículo con placa {datos.plate}",
            {"vehiculo_id": existente.id},
        )
    vehiculo = Vehicle(**datos.model_dump())
    session.add(vehiculo)
    await session.commit()
    await session.refresh(vehiculo)
    log(logger, logging.INFO, "vehiculo.creado", vehicle_id=vehiculo.id, plate=vehiculo.plate)
    return vehiculo


async def obtener_vehiculo(session: AsyncSession, vehiculo_id: str) -> Vehicle:
    vehiculo = await session.get(Vehicle, vehiculo_id)
    if vehiculo is None:
        raise RecursoNoEncontrado(f"No existe el vehículo {vehiculo_id}")
    return vehiculo


async def actualizar_vehiculo(
    session: AsyncSession, vehiculo_id: str, datos: VehiculoActualizar
) -> Vehicle:
    vehiculo = await obtener_vehiculo(session, vehiculo_id)
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(vehiculo, campo, valor)
    await session.commit()
    await session.refresh(vehiculo)
    return vehiculo


async def listar_vehiculos(
    session: AsyncSession,
    estado: Optional[str] = None,
    zona: Optional[str] = None,
    limite: int = 50,
    desplazamiento: int = 0,
) -> Tuple[int, Sequence[Vehicle]]:
    filtros = []
    if estado:
        filtros.append(Vehicle.status == estado)
    if zona:
        filtros.append(Vehicle.zona == zona)

    total = await session.scalar(select(func.count()).select_from(Vehicle).where(*filtros))
    items = (
        (
            await session.execute(
                select(Vehicle)
                .where(*filtros)
                .order_by(Vehicle.plate)
                .limit(limite)
                .offset(desplazamiento)
            )
        )
        .scalars()
        .all()
    )
    return int(total or 0), items


async def buscar_disponibles(
    session: AsyncSession,
    tipo: Optional[str] = None,
    zona: Optional[str] = None,
    capacidad_min_kg: Optional[float] = None,
    volumen_min_m3: Optional[float] = None,
    refrigerado: Optional[bool] = None,
    hazmat: Optional[bool] = None,
    limite: int = 50,
) -> Sequence[Vehicle]:
    """Consulta que hace Routing Service antes de asignar una carga.

    Disponible = estado asignable + seguro vigente + cumple restricciones.
    """
    filtros = [
        Vehicle.status.in_([e.value for e in ESTADOS_ASIGNABLES]),
        Vehicle.insurance_expiry >= date.today(),
    ]
    if tipo:
        filtros.append(Vehicle.type == tipo)
    if zona:
        filtros.append(Vehicle.zona == zona)
    if capacidad_min_kg is not None:
        filtros.append(Vehicle.capacity_kg >= capacidad_min_kg)
    if volumen_min_m3 is not None:
        filtros.append(Vehicle.capacity_m3 >= volumen_min_m3)
    if refrigerado:
        filtros.append(Vehicle.refrigeration_capable.is_(True))
    if hazmat:
        filtros.append(Vehicle.hazmat_certified.is_(True))

    resultado = await session.execute(
        select(Vehicle).where(*filtros).order_by(Vehicle.capacity_kg).limit(limite)
    )
    return resultado.scalars().all()


async def cambiar_estado(
    session: AsyncSession,
    vehiculo: Vehicle,
    nuevo_estado: EstadoVehiculo,
    motivo: Optional[str] = None,
    origen: str = "api",
    hacer_commit: bool = True,
) -> Tuple[Vehicle, bool]:
    """Aplica la transición y encola `vehicle.status_changed` en el outbox.

    Devuelve (vehículo, hubo_cambio). Idempotente: repetir el mismo estado no
    genera un segundo evento.
    """
    anterior = EstadoVehiculo(vehiculo.status)
    if anterior == nuevo_estado:
        return vehiculo, False

    try:
        validar_transicion(anterior, nuevo_estado)
    except TransicionInvalida as exc:
        raise ReglaNegocioViolada(
            str(exc), {"estado_actual": anterior.value, "estado_solicitado": nuevo_estado.value}
        ) from exc

    vehiculo.status = nuevo_estado.value
    vehiculo.motivo_estado = motivo
    vehiculo.actualizado_en = datetime.now(timezone.utc)

    registrar_evento(
        session,
        EVENTO_ESTADO,
        {
            "vehicle_id": vehiculo.id,
            "plate": vehiculo.plate,
            "estado_anterior": anterior.value,
            "estado_nuevo": nuevo_estado.value,
            "asignable": nuevo_estado in ESTADOS_ASIGNABLES,
            "motivo": motivo,
            "zona": vehiculo.zona,
            "origen": origen,
        },
    )
    if hacer_commit:
        # Cambio de estado y evento: misma transacción (patrón Outbox).
        await session.commit()
        await session.refresh(vehiculo)

    cambios_estado.labels(anterior.value, nuevo_estado.value, origen).inc()
    log(
        logger,
        logging.INFO,
        "vehiculo.estado_cambiado",
        vehicle_id=vehiculo.id,
        desde=anterior.value,
        hacia=nuevo_estado.value,
        origen=origen,
    )
    return vehiculo, True


# --------------------------------------------------------------------------
# Conductores
# --------------------------------------------------------------------------
async def crear_conductor(session: AsyncSession, datos: ConductorCrear) -> Driver:
    existente = await session.scalar(
        select(Driver).where(Driver.license_number == datos.license_number)
    )
    if existente:
        raise ConflictoRecurso(
            f"Ya existe un conductor con licencia {datos.license_number}",
            {"conductor_id": existente.id},
        )
    if datos.vehicle_id:
        await obtener_vehiculo(session, datos.vehicle_id)

    conductor = Driver(**datos.model_dump())
    session.add(conductor)
    await session.commit()
    await session.refresh(conductor)
    return conductor


async def obtener_conductor(session: AsyncSession, conductor_id: str) -> Driver:
    conductor = await session.get(Driver, conductor_id)
    if conductor is None:
        raise RecursoNoEncontrado(f"No existe el conductor {conductor_id}")
    return conductor


async def listar_conductores(session: AsyncSession, limite: int = 50) -> Sequence[Driver]:
    return (
        (await session.execute(select(Driver).order_by(Driver.name).limit(limite))).scalars().all()
    )


async def calcular_disponibilidad(
    session: AsyncSession, conductor_id: str
) -> DisponibilidadConductor:
    """Normativa de descanso obligatorio + licencia vigente + estado activo."""
    conductor = await obtener_conductor(session, conductor_id)
    tope = get_settings().horas_max_conduccion_semana
    restantes = max(tope - conductor.hours_driven_week, 0.0)
    licencia_vigente = conductor.license_expiry >= date.today()

    motivos: List[str] = []
    if not conductor.activo:
        motivos.append("conductor_inactivo")
    if not licencia_vigente:
        motivos.append("licencia_vencida")
    if restantes <= 0:
        motivos.append("tope_horas_semanales_alcanzado")

    return DisponibilidadConductor(
        conductor_id=conductor.id,
        disponible=not motivos,
        horas_conducidas_semana=conductor.hours_driven_week,
        horas_restantes=restantes,
        licencia_vigente=licencia_vigente,
        motivos=motivos,
    )


async def asignar_vehiculo(
    session: AsyncSession, conductor_id: str, vehicle_id: Optional[str]
) -> Driver:
    conductor = await obtener_conductor(session, conductor_id)
    if vehicle_id:
        vehiculo = await obtener_vehiculo(session, vehicle_id)
        if EstadoVehiculo(vehiculo.status) not in ESTADOS_ASIGNABLES:
            raise ReglaNegocioViolada(
                f"El vehículo {vehiculo.plate} está en estado '{vehiculo.status}' "
                "y no admite asignación",
                {"estado": vehiculo.status},
            )
    conductor.vehicle_id = vehicle_id
    await session.commit()
    await session.refresh(conductor)
    return conductor


async def registrar_horas(session: AsyncSession, conductor_id: str, horas: float) -> Driver:
    conductor = await obtener_conductor(session, conductor_id)
    conductor.hours_driven_week = round(conductor.hours_driven_week + horas, 2)
    await session.commit()
    await session.refresh(conductor)
    return conductor
