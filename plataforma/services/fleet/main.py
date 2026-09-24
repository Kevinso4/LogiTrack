"""Fleet Service — maestro de vehículos y conductores.

REST:     catálogo, disponibilidad (consultada por Shipment) y cambios de estado.
Publica:  vehicle.status_changed
Consume:  maintenance.alert, maintenance.completed, shipment.incident,
          shipment.assigned, shipment.reassigned, shipment.delivered, shipment.returned
"""
import logging
import uuid
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.app import crear_app
from common.db import ahora, get_db
from common.errores import error
from common.outbox import idempotente, registrar_evento
from common.seguridad import requiere_rol

from .models import Asignacion, Conductor, ConductorCategoria, EstadoVehiculo, TipoVehiculo, Vehiculo
from .schemas import (
    AsignacionIn,
    CambioEstadoIn,
    ConductorIn,
    ConductorOut,
    ConductorResumen,
    VehiculoIn,
    VehiculoOut,
)
from .seed import sembrar

log = logging.getLogger("fleet")
Db = Annotated[Session, Depends(get_db)]


# ---------------------------------------------------------------- dominio


def cambiar_estado(db: Session, vehiculo: Vehiculo, nuevo: EstadoVehiculo, motivo: str) -> bool:
    """Cambia el estado y deja vehicle.status_changed en la outbox, en la misma transacción."""
    if vehiculo.estado == nuevo:
        return False
    anterior = vehiculo.estado
    vehiculo.estado = nuevo
    registrar_evento(
        db,
        "vehicle.status_changed",
        vehiculo.id,
        {
            "vehiculo_id": vehiculo.id,
            "placa": vehiculo.placa,
            "estado_anterior": anterior.value,
            "estado_nuevo": nuevo.value,
            "motivo": motivo,
        },
    )
    log.info("Vehículo %s: %s -> %s (%s)", vehiculo.placa, anterior.value, nuevo.value, motivo,
             extra={"vehicle_id": str(vehiculo.id)})
    return True


def conductor_vigente(db: Session, vehiculo_id: uuid.UUID) -> Conductor | None:
    asig = db.scalar(
        select(Asignacion).where(Asignacion.vehiculo_id == vehiculo_id, Asignacion.hasta.is_(None))
    )
    return asig.conductor if asig else None


def a_salida(db: Session, v: Vehiculo) -> VehiculoOut:
    salida = VehiculoOut.model_validate(v)
    c = conductor_vigente(db, v.id)
    salida.conductor = ConductorResumen.model_validate(c) if c else None
    return salida


def obtener(db: Session, vehiculo_id) -> Vehiculo:
    v = db.get(Vehiculo, vehiculo_id)
    if not v:
        raise error(404, "vehiculo_no_encontrado", "El vehículo no existe")
    return v


# ---------------------------------------------------------------- consumidores


def _vehiculo_de(db: Session, datos: dict) -> Vehiculo | None:
    vid = datos.get("vehiculo_id")
    return db.get(Vehiculo, uuid.UUID(vid)) if vid else None


@idempotente
def al_alerta_mantenimiento(db: Session, evento: dict) -> None:
    datos = evento["datos"]
    v = _vehiculo_de(db, datos)
    if v and datos.get("critica") and v.estado != EstadoVehiculo.fuera_de_servicio:
        cambiar_estado(db, v, EstadoVehiculo.en_mantenimiento, f"Alerta de mantenimiento: {datos.get('mensaje')}")


@idempotente
def al_mantenimiento_completado(db: Session, evento: dict) -> None:
    v = _vehiculo_de(db, evento["datos"])
    if v and v.estado in (EstadoVehiculo.en_mantenimiento, EstadoVehiculo.fuera_de_servicio):
        cambiar_estado(db, v, EstadoVehiculo.activo, "Intervención de mantenimiento registrada")


@idempotente
def al_incidente_envio(db: Session, evento: dict) -> None:
    datos = evento["datos"]
    v = _vehiculo_de(db, datos)
    # Solo una avería o accidente sacan al vehículo de servicio; un retraso por tráfico no.
    if v and datos.get("tipo") in ("averia", "accidente"):
        cambiar_estado(db, v, EstadoVehiculo.fuera_de_servicio, f"Incidencia en envío: {datos.get('tipo')}")


@idempotente
def al_envio_asignado(db: Session, evento: dict) -> None:
    v = _vehiculo_de(db, evento["datos"])
    if v and v.estado == EstadoVehiculo.activo:
        cambiar_estado(db, v, EstadoVehiculo.en_transito, f"Asignado al envío {evento['datos'].get('codigo')}")


@idempotente
def al_envio_entregado(db: Session, evento: dict) -> None:
    v = _vehiculo_de(db, evento["datos"])
    if v and v.estado == EstadoVehiculo.en_transito:
        cambiar_estado(db, v, EstadoVehiculo.activo, "Envío finalizado, vehículo liberado")


app = crear_app(
    "fleet",
    "LogiTrack · Fleet Service",
    suscripciones=[
        ("maintenance-alert", ["maintenance.alert"], al_alerta_mantenimiento),
        ("maintenance-completed", ["maintenance.completed"], al_mantenimiento_completado),
        ("shipment-incident", ["shipment.incident"], al_incidente_envio),
        ("shipment-assigned", ["shipment.assigned", "shipment.reassigned"], al_envio_asignado),
        ("shipment-finished", ["shipment.delivered", "shipment.returned"], al_envio_entregado),
    ],
    al_iniciar=sembrar,
)

# ---------------------------------------------------------------- vehículos


@app.get("/api/v1/vehiculos", response_model=list[VehiculoOut], tags=["vehículos"])
def listar_vehiculos(
    db: Db,
    estado: EstadoVehiculo | None = None,
    tipo: TipoVehiculo | None = None,
    q: str | None = Query(default=None, max_length=40),
):
    consulta = select(Vehiculo).order_by(Vehiculo.placa)
    if estado:
        consulta = consulta.where(Vehiculo.estado == estado)
    if tipo:
        consulta = consulta.where(Vehiculo.tipo == tipo)
    if q:
        consulta = consulta.where(Vehiculo.placa.ilike(f"%{q}%") | Vehiculo.marca.ilike(f"%{q}%"))
    return [a_salida(db, v) for v in db.scalars(consulta)]


@app.get("/api/v1/vehiculos/resumen", tags=["vehículos"])
def resumen(db: Db):
    filas = db.execute(select(Vehiculo.estado, func.count()).group_by(Vehiculo.estado)).all()
    conteo = {e.value: 0 for e in EstadoVehiculo}
    conteo.update({estado.value: n for estado, n in filas})
    return {"total": sum(conteo.values()), "por_estado": conteo}


@app.get("/api/v1/vehiculos/disponibles", response_model=list[VehiculoOut], tags=["vehículos"])
def disponibles(
    db: Db,
    tipo: TipoVehiculo | None = None,
    zona: str | None = None,
    refrigerado: bool = False,
    hazmat: bool = False,
    peso_kg: float = Query(default=0, ge=0),
    volumen_m3: float = Query(default=0, ge=0),
):
    """Qué vehículos activos cumplen los requisitos de una carga (consulta síncrona de Shipment)."""
    consulta = select(Vehiculo).where(
        Vehiculo.estado == EstadoVehiculo.activo,
        Vehiculo.capacidad_kg >= peso_kg,
        Vehiculo.capacidad_m3 >= volumen_m3,
    )
    if tipo:
        consulta = consulta.where(Vehiculo.tipo == tipo)
    if zona:
        consulta = consulta.where(Vehiculo.zona.ilike(zona))
    if refrigerado:
        consulta = consulta.where(Vehiculo.refrigerado.is_(True))
    if hazmat:
        consulta = consulta.where(Vehiculo.certificado_hazmat.is_(True))
    # El vehículo más pequeño que cumple deja libres los grandes para cargas grandes.
    consulta = consulta.order_by(Vehiculo.capacidad_kg, Vehiculo.placa)
    return [a_salida(db, v) for v in db.scalars(consulta)]


@app.get("/api/v1/vehiculos/{vehiculo_id}", response_model=VehiculoOut, tags=["vehículos"])
def ver_vehiculo(vehiculo_id: uuid.UUID, db: Db):
    return a_salida(db, obtener(db, vehiculo_id))


@app.post("/api/v1/vehiculos", response_model=VehiculoOut, status_code=201, tags=["vehículos"])
def crear_vehiculo(datos: VehiculoIn, db: Db, _=requiere_rol("gestor_flota")):
    v = Vehiculo(**datos.model_dump())
    db.add(v)
    try:
        db.flush()
        registrar_evento(
            db, "vehicle.status_changed", v.id,
            {"vehiculo_id": v.id, "placa": v.placa, "estado_anterior": None, "estado_nuevo": "activo",
             "motivo": "Alta de vehículo"},
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise error(409, "placa_duplicada", f"Ya existe un vehículo con placa {datos.placa}")
    return a_salida(db, v)


@app.patch("/api/v1/vehiculos/{vehiculo_id}/estado", response_model=VehiculoOut, tags=["vehículos"])
def cambiar_estado_vehiculo(
    vehiculo_id: uuid.UUID, datos: CambioEstadoIn, db: Db, _=requiere_rol("gestor_flota", "operador")
):
    v = obtener(db, vehiculo_id)
    cambiar_estado(db, v, datos.estado, datos.motivo)
    db.commit()
    return a_salida(db, v)


# ---------------------------------------------------------------- conductores


def conductor_salida(db: Session, c: Conductor) -> ConductorOut:
    salida = ConductorOut.model_validate(c)
    asig = db.scalar(select(Asignacion).where(Asignacion.conductor_id == c.id, Asignacion.hasta.is_(None)))
    salida.vehiculo_placa = asig.vehiculo.placa if asig else None
    return salida


@app.get("/api/v1/conductores", response_model=list[ConductorOut], tags=["conductores"])
def listar_conductores(db: Db):
    return [conductor_salida(db, c) for c in db.scalars(select(Conductor).order_by(Conductor.nombre))]


@app.post("/api/v1/conductores", response_model=ConductorOut, status_code=201, tags=["conductores"])
def crear_conductor(datos: ConductorIn, db: Db, _=requiere_rol("gestor_flota")):
    c = Conductor(**datos.model_dump(exclude={"categorias"}))
    c.categorias = [ConductorCategoria(categoria=cat.upper()[:4]) for cat in set(datos.categorias)]
    db.add(c)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise error(409, "licencia_duplicada", "Ya existe un conductor con esa licencia")
    return conductor_salida(db, c)


@app.get("/api/v1/conductores/{conductor_id}/disponibilidad", tags=["conductores"])
def disponibilidad_conductor(conductor_id: uuid.UUID, db: Db):
    c = db.get(Conductor, conductor_id)
    if not c:
        raise error(404, "conductor_no_encontrado", "El conductor no existe")
    horas = float(c.horas_conducidas_semana)
    return {
        "conductor_id": c.id,
        "horas_conducidas_semana": horas,
        "horas_restantes": max(0.0, 60 - horas),
        "disponible": horas < 60,
    }


@app.post("/api/v1/asignaciones", status_code=201, tags=["conductores"])
def asignar_conductor(datos: AsignacionIn, db: Db, _=requiere_rol("gestor_flota")):
    obtener(db, datos.vehiculo_id)
    if not db.get(Conductor, datos.conductor_id):
        raise error(404, "conductor_no_encontrado", "El conductor no existe")
    # Cierra la asignación vigente del vehículo y la del conductor antes de abrir la nueva.
    for asig in db.scalars(
        select(Asignacion).where(
            Asignacion.hasta.is_(None),
            (Asignacion.vehiculo_id == datos.vehiculo_id) | (Asignacion.conductor_id == datos.conductor_id),
        )
    ):
        asig.hasta = ahora()
    nueva = Asignacion(vehiculo_id=datos.vehiculo_id, conductor_id=datos.conductor_id)
    db.add(nueva)
    db.commit()
    return {"id": nueva.id, "vehiculo_id": nueva.vehiculo_id, "conductor_id": nueva.conductor_id}
