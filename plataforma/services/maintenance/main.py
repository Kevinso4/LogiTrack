"""Maintenance Service — mantenimiento preventivo y alertas de anomalías.

Consume:  telemetry.aggregated  → evalúa reglas por métrica y programa mantenimiento preventivo.
Publica:  maintenance.alert, maintenance.scheduled, maintenance.completed   (vía outbox)
Nunca toca la BD de Tracking: solo procesa el evento agregado que le llega.
"""
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.app import crear_app
from common.db import SessionLocal, ahora, get_db
from common.errores import error
from common.outbox import idempotente, registrar_evento
from common.seguridad import requiere_rol

from .models import (
    Alerta,
    EstadoAlerta,
    EstadoPrograma,
    Intervencion,
    Metrica,
    Operador,
    ProgramaMantenimiento,
    Regla,
    UltimaLectura,
)

log = logging.getLogger("maintenance")
Db = Annotated[Session, Depends(get_db)]

INTERVALO_PREVENTIVO_KM = 10_000
INTERVALO_PREVENTIVO_DIAS = 60

REGLAS_INICIALES = [
    ("Sobrecalentamiento de motor", Metrica.temperatura_motor, Operador.mayor, 105, 1),
    ("Código de diagnóstico OBD2 activo", Metrica.codigo_obd2, Operador.presente, 0, 1),
    ("Exceso de velocidad", Metrica.velocidad, Operador.mayor, 110, 2),
    ("Cadena de frío rota (carga > 8 °C)", Metrica.temperatura_carga, Operador.mayor, 8, 2),
    ("Combustible en reserva", Metrica.nivel_combustible, Operador.menor, 10, 3),
]

UNIDADES = {
    Metrica.temperatura_motor: "°C",
    Metrica.velocidad: "km/h",
    Metrica.temperatura_carga: "°C",
    Metrica.nivel_combustible: "%",
    Metrica.codigo_obd2: "",
}


def sembrar_reglas() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Regla.id).limit(1)):
            return
        db.add_all(
            Regla(nombre=n, metrica=m, operador=o, umbral=u, prioridad=p) for n, m, o, u, p in REGLAS_INICIALES
        )
        db.commit()


# ---------------------------------------------------------------- motor de reglas


def evaluar(regla: Regla, valor) -> bool:
    if valor is None:
        return False
    if regla.operador == Operador.presente:
        return bool(valor)
    if regla.operador == Operador.mayor:
        return float(valor) > float(regla.umbral)
    return float(valor) < float(regla.umbral)


def programar(db: Session, vehiculo_id: uuid.UUID, tipo: str, fecha: date, km: int | None, prioridad: int = 2):
    prog = ProgramaMantenimiento(vehiculo_id=vehiculo_id, tipo=tipo, fecha_prevista=fecha, km_previsto=km,
                                 prioridad=prioridad)
    db.add(prog)
    db.flush()
    registrar_evento(db, "maintenance.scheduled", prog.id,
                     {"programa_id": prog.id, "vehiculo_id": vehiculo_id, "tipo": tipo,
                      "fecha_prevista": fecha, "km_previsto": km})
    return prog


@idempotente
def al_telemetria(db: Session, evento: dict) -> None:
    d = evento["datos"]
    vid = uuid.UUID(d["vehiculo_id"])

    lectura = db.get(UltimaLectura, vid) or UltimaLectura(vehiculo_id=vid)
    lectura.odometro_km = d["odometro_km"]
    lectura.temperatura_motor_max = d["temperatura_motor_max"]
    lectura.nivel_combustible = d["nivel_combustible"]
    lectura.actualizado_en = ahora()
    db.merge(lectura)

    # Mantenimiento preventivo automático: todo vehículo que reporta tiene un próximo servicio programado.
    tiene_programa = db.scalar(
        select(ProgramaMantenimiento.id).where(
            ProgramaMantenimiento.vehiculo_id == vid, ProgramaMantenimiento.estado == EstadoPrograma.programado
        ).limit(1)
    )
    if not tiene_programa:
        km = (int(d["odometro_km"]) // INTERVALO_PREVENTIVO_KM + 1) * INTERVALO_PREVENTIVO_KM
        programar(db, vid, "Revisión preventiva: aceite, filtros y frenos",
                  date.today() + timedelta(days=INTERVALO_PREVENTIVO_DIAS), km)

    valores = {
        Metrica.temperatura_motor: d.get("temperatura_motor_max"),
        Metrica.nivel_combustible: d.get("nivel_combustible"),
        Metrica.velocidad: d.get("velocidad_max"),
        Metrica.temperatura_carga: d.get("temperatura_carga_max"),
        Metrica.codigo_obd2: ", ".join(d.get("codigos_obd2") or []),
    }
    abiertas = set(
        db.scalars(select(Alerta.regla_id).where(Alerta.vehiculo_id == vid, Alerta.estado == EstadoAlerta.abierta))
    )
    for regla in db.scalars(select(Regla).where(Regla.activa.is_(True))):
        valor = valores[regla.metrica]
        if regla.id in abiertas or not evaluar(regla, valor):
            continue
        texto_valor = f"{valor} {UNIDADES[regla.metrica]}".strip()
        alerta = Alerta(
            vehiculo_id=vid, regla_id=regla.id, metrica=regla.metrica, valor=texto_valor[:40],
            mensaje=f"{regla.nombre}: {texto_valor}", prioridad=regla.prioridad,
        )
        db.add(alerta)
        db.flush()
        registrar_evento(db, "maintenance.alert", alerta.id, {
            "alerta_id": alerta.id, "vehiculo_id": vid, "metrica": regla.metrica.value, "valor": texto_valor,
            "umbral": float(regla.umbral), "mensaje": alerta.mensaje, "prioridad": regla.prioridad,
            "critica": regla.prioridad == 1,
        })
        log.warning("Alerta: %s", alerta.mensaje, extra={"vehicle_id": str(vid)})


app = crear_app(
    "maintenance",
    "LogiTrack · Maintenance Service",
    suscripciones=[("telemetry", ["telemetry.aggregated"], al_telemetria)],
    al_iniciar=sembrar_reglas,
)


# ---------------------------------------------------------------- esquemas


class AlertaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    vehiculo_id: uuid.UUID
    metrica: Metrica
    valor: str
    mensaje: str
    prioridad: int
    estado: EstadoAlerta
    creada_en: datetime
    cerrada_en: datetime | None


class ProgramaIn(BaseModel):
    vehiculo_id: uuid.UUID
    tipo: str = Field(min_length=3, max_length=80)
    fecha_prevista: date
    km_previsto: int | None = Field(default=None, ge=0)
    prioridad: int = Field(default=2, ge=1, le=3)


class ProgramaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    vehiculo_id: uuid.UUID
    tipo: str
    fecha_prevista: date
    km_previsto: int | None
    prioridad: int
    estado: EstadoPrograma
    km_actual: float | None = None
    km_restantes: float | None = None
    dias_restantes: int | None = None


class IntervencionIn(BaseModel):
    vehiculo_id: uuid.UUID
    programa_id: uuid.UUID | None = None
    descripcion: str = Field(min_length=3, max_length=1000)
    costo: float = Field(ge=0, le=1_000_000_000)
    taller: str = Field(min_length=2, max_length=120)
    km_al_servicio: int = Field(ge=0)


class IntervencionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    vehiculo_id: uuid.UUID
    programa_id: uuid.UUID | None
    descripcion: str
    realizado_en: datetime
    costo: float
    taller: str
    km_al_servicio: int


class ReglaIn(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    metrica: Metrica
    operador: Operador
    umbral: float = 0
    prioridad: int = Field(default=2, ge=1, le=3)
    tipo_vehiculo: str | None = None


class ReglaPatch(BaseModel):
    umbral: float | None = None
    prioridad: int | None = Field(default=None, ge=1, le=3)
    activa: bool | None = None


class ReglaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nombre: str
    metrica: Metrica
    operador: Operador
    umbral: float
    prioridad: int
    activa: bool
    tipo_vehiculo: str | None


def programa_salida(db: Session, p: ProgramaMantenimiento) -> ProgramaOut:
    salida = ProgramaOut.model_validate(p)
    lectura = db.get(UltimaLectura, p.vehiculo_id)
    if lectura:
        salida.km_actual = float(lectura.odometro_km)
        if p.km_previsto is not None:
            salida.km_restantes = round(p.km_previsto - float(lectura.odometro_km), 1)
    salida.dias_restantes = (p.fecha_prevista - date.today()).days
    return salida


# ---------------------------------------------------------------- alertas


@app.get("/api/v1/mantenimiento/alertas", response_model=list[AlertaOut], tags=["alertas"])
def alertas(
    db: Db,
    estado: EstadoAlerta | None = None,
    vehiculo_id: uuid.UUID | None = None,
    limite: int = Query(default=100, ge=1, le=500),
):
    consulta = select(Alerta).order_by(Alerta.creada_en.desc()).limit(limite)
    if estado:
        consulta = consulta.where(Alerta.estado == estado)
    if vehiculo_id:
        consulta = consulta.where(Alerta.vehiculo_id == vehiculo_id)
    return list(db.scalars(consulta))


@app.post("/api/v1/mantenimiento/alertas/{alerta_id}/cerrar", response_model=AlertaOut, tags=["alertas"])
def cerrar_alerta(alerta_id: uuid.UUID, db: Db, _=requiere_rol("gestor_flota")):
    alerta = db.get(Alerta, alerta_id)
    if not alerta:
        raise error(404, "alerta_no_encontrada", "La alerta no existe")
    if alerta.estado == EstadoAlerta.abierta:
        alerta.estado = EstadoAlerta.cerrada
        alerta.cerrada_en = ahora()
        db.commit()
    return alerta


# ---------------------------------------------------------------- programas


@app.get("/api/v1/mantenimiento/proximos", response_model=list[ProgramaOut], tags=["programas"])
def proximos(db: Db, dias: int = Query(default=90, ge=1, le=365)):
    consulta = (
        select(ProgramaMantenimiento)
        .where(
            ProgramaMantenimiento.estado == EstadoPrograma.programado,
            ProgramaMantenimiento.fecha_prevista <= date.today() + timedelta(days=dias),
        )
        .order_by(ProgramaMantenimiento.fecha_prevista)
    )
    return [programa_salida(db, p) for p in db.scalars(consulta)]


@app.post("/api/v1/mantenimiento/programas", response_model=ProgramaOut, status_code=201, tags=["programas"])
def crear_programa(datos: ProgramaIn, db: Db, _=requiere_rol("gestor_flota")):
    prog = programar(db, datos.vehiculo_id, datos.tipo, datos.fecha_prevista, datos.km_previsto, datos.prioridad)
    db.commit()
    return programa_salida(db, prog)


@app.get("/api/v1/mantenimiento/vehiculo/{vehiculo_id}/programa", tags=["programas"])
def programa_vehiculo(vehiculo_id: uuid.UUID, db: Db):
    programas = db.scalars(
        select(ProgramaMantenimiento)
        .where(ProgramaMantenimiento.vehiculo_id == vehiculo_id)
        .order_by(ProgramaMantenimiento.fecha_prevista.desc())
    )
    intervenciones = db.scalars(
        select(Intervencion).where(Intervencion.vehiculo_id == vehiculo_id).order_by(Intervencion.realizado_en.desc())
    )
    alertas_v = db.scalars(
        select(Alerta).where(Alerta.vehiculo_id == vehiculo_id).order_by(Alerta.creada_en.desc()).limit(50)
    )
    return {
        "vehiculo_id": vehiculo_id,
        "programas": [programa_salida(db, p) for p in programas],
        "intervenciones": [IntervencionOut.model_validate(i) for i in intervenciones],
        "alertas": [AlertaOut.model_validate(a) for a in alertas_v],
    }


# ---------------------------------------------------------------- intervenciones


@app.get("/api/v1/mantenimiento/intervenciones", response_model=list[IntervencionOut], tags=["intervenciones"])
def listar_intervenciones(db: Db, vehiculo_id: uuid.UUID | None = None):
    consulta = select(Intervencion).order_by(Intervencion.realizado_en.desc()).limit(200)
    if vehiculo_id:
        consulta = consulta.where(Intervencion.vehiculo_id == vehiculo_id)
    return list(db.scalars(consulta))


@app.post("/api/v1/mantenimiento/intervenciones", response_model=IntervencionOut, status_code=201,
          tags=["intervenciones"])
def registrar_intervencion(datos: IntervencionIn, db: Db, _=requiere_rol("gestor_flota")):
    """Registra el servicio, cierra las alertas abiertas y devuelve el vehículo a operación."""
    if datos.programa_id:
        prog = db.get(ProgramaMantenimiento, datos.programa_id)
        if not prog or prog.vehiculo_id != datos.vehiculo_id:
            raise error(404, "programa_no_encontrado", "El programa no existe para ese vehículo")
        prog.estado = EstadoPrograma.completado
    intervencion = Intervencion(**datos.model_dump())
    db.add(intervencion)
    cerradas = 0
    for alerta in db.scalars(
        select(Alerta).where(Alerta.vehiculo_id == datos.vehiculo_id, Alerta.estado == EstadoAlerta.abierta)
    ):
        alerta.estado = EstadoAlerta.cerrada
        alerta.cerrada_en = ahora()
        cerradas += 1
    db.flush()
    registrar_evento(db, "maintenance.completed", intervencion.id, {
        "intervencion_id": intervencion.id, "vehiculo_id": datos.vehiculo_id, "descripcion": datos.descripcion,
        "costo": datos.costo, "alertas_cerradas": cerradas,
    })
    db.commit()
    return intervencion


# ---------------------------------------------------------------- reglas


@app.get("/api/v1/mantenimiento/reglas", response_model=list[ReglaOut], tags=["reglas"])
def listar_reglas(db: Db):
    return list(db.scalars(select(Regla).order_by(Regla.prioridad, Regla.nombre)))


@app.post("/api/v1/mantenimiento/reglas", response_model=ReglaOut, status_code=201, tags=["reglas"])
def crear_regla(datos: ReglaIn, db: Db, _=requiere_rol("gestor_flota")):
    regla = Regla(**datos.model_dump())
    db.add(regla)
    db.commit()
    return regla


@app.patch("/api/v1/mantenimiento/reglas/{regla_id}", response_model=ReglaOut, tags=["reglas"])
def editar_regla(regla_id: uuid.UUID, datos: ReglaPatch, db: Db, _=requiere_rol("gestor_flota")):
    regla = db.get(Regla, regla_id)
    if not regla:
        raise error(404, "regla_no_encontrada", "La regla no existe")
    for campo, valor in datos.model_dump(exclude_none=True).items():
        setattr(regla, campo, valor)
    db.commit()
    return regla


@app.get("/api/v1/mantenimiento/resumen", tags=["alertas"])
def resumen(db: Db):
    abiertas = db.execute(
        select(Alerta.prioridad, func.count()).where(Alerta.estado == EstadoAlerta.abierta).group_by(Alerta.prioridad)
    ).all()
    por_prioridad = {p: n for p, n in abiertas}
    inicio_mes = date.today().replace(day=1)
    costo_mes = db.scalar(select(func.coalesce(func.sum(Intervencion.costo), 0)).where(
        Intervencion.realizado_en >= inicio_mes))
    proximos_30 = db.scalar(select(func.count()).where(
        ProgramaMantenimiento.estado == EstadoPrograma.programado,
        ProgramaMantenimiento.fecha_prevista <= date.today() + timedelta(days=30)))
    return {
        "alertas_abiertas": sum(por_prioridad.values()),
        "alertas_criticas": por_prioridad.get(1, 0),
        "programas_proximos_30_dias": proximos_30,
        "costo_mes": float(costo_mes),
    }
