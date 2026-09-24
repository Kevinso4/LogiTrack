"""Shipment Service — núcleo transaccional: ciclo de vida del envío y cadena de custodia.

REST:     crear, consultar, incidencia, prueba de entrega, seguimiento público.
          Consulta a Fleet por REST síncrono qué vehículos cumplen la carga.
Publica:  shipment.created, shipment.assigned, shipment.reassigned, shipment.incident,
          shipment.delayed, shipment.delivered, shipment.returned   (vía outbox)
Consume:  vehicle.status_changed  → saga de reasignación y su compensación.
"""
import asyncio
import logging
import os
import secrets
import string
import threading
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from common.app import crear_app
from common.cliente_http import ClienteServicio
from common.db import SessionLocal, ahora, get_db
from common.errores import error
from common.outbox import idempotente, registrar_evento
from common.seguridad import requiere_rol

from .models import Envio, EstadoEnvio, EventoEnvio, PruebaEntrega, TipoEventoEnvio
from .schemas import (
    EnvioDetalleOut,
    EnvioIn,
    EnvioOut,
    IncidenciaIn,
    NotaIn,
    PruebaEntregaIn,
    SeguimientoOut,
)

log = logging.getLogger("shipment")
Db = Annotated[Session, Depends(get_db)]

fleet = ClienteServicio("fleet", os.getenv("FLEET_URL", "http://fleet:8000"))
# Evita que dos asignaciones simultáneas elijan el mismo vehículo antes de que Fleet
# reciba shipment.assigned (ventana de consistencia eventual). Una réplica por servicio.
_candado_asignacion = threading.Lock()

ACTIVOS = (EstadoEnvio.en_transito, EstadoEnvio.con_incidencia)


# ---------------------------------------------------------------- dominio


def registrar(db: Session, envio: Envio, tipo: TipoEventoEnvio, notas: str | None = None) -> None:
    db.add(EventoEnvio(envio_id=envio.id, tipo_evento=tipo, notas=notas))


def datos_evento(envio: Envio, **extra) -> dict:
    return {
        "envio_id": envio.id,
        "codigo": envio.codigo,
        "cliente": envio.cliente,
        "cliente_email": envio.cliente_email,
        "origen": envio.origen,
        "destino": envio.destino,
        "estado": envio.estado.value,
        "vehiculo_id": envio.vehiculo_id,
        "placa": envio.vehiculo_placa,
        "es_internacional": envio.es_internacional,
        **extra,
    }


def buscar_vehiculo(db: Session, envio: Envio, excluir: set[uuid.UUID] = frozenset()) -> dict | None:
    """REST síncrono a Fleet: primero en la zona de origen, luego en cualquier zona."""
    ocupados = set(
        db.scalars(select(Envio.vehiculo_id).where(Envio.estado.in_(ACTIVOS), Envio.vehiculo_id.is_not(None)))
    )
    descartados = ocupados | set(excluir)
    for zona in (envio.origen, None):
        resp = fleet.get(
            "/api/v1/vehiculos/disponibles",
            zona=zona,
            peso_kg=float(envio.peso_kg),
            volumen_m3=float(envio.volumen_m3),
            refrigerado=str(envio.requiere_refrigeracion).lower(),
            hazmat=str(envio.es_hazmat).lower(),
        )
        resp.raise_for_status()
        for v in resp.json():
            if uuid.UUID(v["id"]) not in descartados:
                return v
    return None


def asignar_envio(envio_id: uuid.UUID) -> None:
    """Intenta asignar vehículo a un envío pendiente o retrasado."""
    with _candado_asignacion, SessionLocal() as db:
        envio = db.get(Envio, envio_id, with_for_update=True)
        if not envio or envio.estado not in (EstadoEnvio.pendiente, EstadoEnvio.retrasado):
            return
        try:
            v = buscar_vehiculo(db, envio)
        except Exception as exc:  # Fleet caído o circuito abierto: se reintenta luego
            log.warning("Fleet no respondió al asignar %s: %s", envio.codigo, exc,
                        extra={"shipment_id": str(envio.id)})
            return
        if v:
            envio.vehiculo_id = uuid.UUID(v["id"])
            envio.vehiculo_placa = v["placa"]
            envio.estado = EstadoEnvio.en_transito
            registrar(db, envio, TipoEventoEnvio.asignado, f"Vehículo {v['placa']} asignado")
            registrar_evento(db, "shipment.assigned", envio.id, datos_evento(envio))
            log.info("Envío %s asignado a %s", envio.codigo, v["placa"], extra={"shipment_id": str(envio.id)})
        elif envio.estado == EstadoEnvio.pendiente:
            envio.estado = EstadoEnvio.retrasado
            registrar(db, envio, TipoEventoEnvio.retrasado, "No hay vehículos disponibles que cumplan la carga")
            registrar_evento(db, "shipment.delayed", envio.id,
                             datos_evento(envio, motivo="Sin vehículos disponibles"))
        db.commit()


def generar_codigo(db: Session) -> str:
    alfabeto = string.ascii_uppercase + string.digits
    while True:
        codigo = "LT-" + "".join(secrets.choice(alfabeto) for _ in range(6))
        if not db.scalar(select(Envio.id).where(Envio.codigo == codigo)):
            return codigo


def obtener(db: Session, envio_id: uuid.UUID, bloquear: bool = False) -> Envio:
    envio = db.get(Envio, envio_id, with_for_update=bloquear)
    if not envio:
        raise error(404, "envio_no_encontrado", "El envío no existe")
    return envio


def exigir_estado(envio: Envio, *permitidos: EstadoEnvio) -> None:
    if envio.estado not in permitidos:
        raise error(
            409,
            "transicion_invalida",
            f"El envío está '{envio.estado.value}' y la acción requiere: {', '.join(e.value for e in permitidos)}",
        )


# ---------------------------------------------------------------- saga


@idempotente
def al_cambio_estado_vehiculo(db: Session, evento: dict) -> None:
    """Pasos 4-6 de la saga de avería y su compensación (a-c).

    Cuando un vehículo sale de servicio, sus envíos activos buscan un vehículo alternativo.
    Si no hay ninguno, se compensa: el envío queda retrasado y se libera la carga.
    """
    datos = evento["datos"]
    if datos.get("estado_nuevo") not in ("fuera_de_servicio", "en_mantenimiento"):
        return
    vehiculo_id = uuid.UUID(datos["vehiculo_id"])
    with _candado_asignacion:
        afectados = list(
            db.scalars(
                select(Envio).where(Envio.vehiculo_id == vehiculo_id, Envio.estado.in_(ACTIVOS)).with_for_update()
            )
        )
        for envio in afectados:
            placa_anterior = envio.vehiculo_placa
            v = buscar_vehiculo(db, envio, excluir={vehiculo_id})
            if v:
                envio.vehiculo_id = uuid.UUID(v["id"])
                envio.vehiculo_placa = v["placa"]
                envio.estado = EstadoEnvio.en_transito
                registrar(db, envio, TipoEventoEnvio.reasignado,
                          f"{placa_anterior} → {v['placa']} ({datos.get('motivo')})")
                registrar_evento(db, "shipment.reassigned", envio.id,
                                 datos_evento(envio, vehiculo_anterior_id=vehiculo_id, placa_anterior=placa_anterior))
                log.info("Saga: envío %s reasignado %s -> %s", envio.codigo, placa_anterior, v["placa"],
                         extra={"shipment_id": str(envio.id)})
            else:
                envio.vehiculo_id = None
                envio.vehiculo_placa = None
                envio.estado = EstadoEnvio.retrasado
                registrar(db, envio, TipoEventoEnvio.retrasado,
                          f"Compensación: sin vehículo alternativo tras salida de {placa_anterior}")
                registrar_evento(db, "shipment.delayed", envio.id,
                                 datos_evento(envio, motivo="Sin vehículo alternativo", placa_anterior=placa_anterior))
                log.warning("Saga: compensación, envío %s retrasado", envio.codigo,
                            extra={"shipment_id": str(envio.id)})
        db.flush()


async def reintentar_asignaciones(_bus, parar: asyncio.Event) -> None:
    """Cada 15 s reintenta los envíos pendientes o retrasados (p. ej. cuando se libera un vehículo)."""
    while not parar.is_set():
        await asyncio.sleep(15)
        try:
            with SessionLocal() as db:
                ids = list(
                    db.scalars(
                        select(Envio.id)
                        .where(Envio.estado.in_((EstadoEnvio.pendiente, EstadoEnvio.retrasado)))
                        .order_by(Envio.fecha_limite_sla)
                        .limit(20)
                    )
                )
            for envio_id in ids:
                await run_in_threadpool(asignar_envio, envio_id)
        except Exception:
            log.exception("Fallo reintentando asignaciones")


app = crear_app(
    "shipment",
    "LogiTrack · Shipment Service",
    suscripciones=[("vehicle-status", ["vehicle.status_changed"], al_cambio_estado_vehiculo)],
    tareas=[reintentar_asignaciones],
)


# ---------------------------------------------------------------- consultas


@app.get("/api/v1/envios", response_model=list[EnvioOut], tags=["envíos"])
def listar(
    db: Db,
    estado: EstadoEnvio | None = None,
    vehiculo_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=60),
    limite: int = Query(default=100, ge=1, le=500),
):
    consulta = select(Envio).order_by(Envio.creado_en.desc()).limit(limite)
    if estado:
        consulta = consulta.where(Envio.estado == estado)
    if vehiculo_id:
        consulta = consulta.where(Envio.vehiculo_id == vehiculo_id)
    if q:
        patron = f"%{q}%"
        consulta = consulta.where(
            or_(Envio.codigo.ilike(patron), Envio.cliente.ilike(patron), Envio.destino.ilike(patron))
        )
    return list(db.scalars(consulta))


@app.get("/api/v1/envios/resumen", tags=["envíos"])
def resumen(db: Db):
    filas = db.execute(select(Envio.estado, func.count()).group_by(Envio.estado)).all()
    conteo = {e.value: 0 for e in EstadoEnvio}
    conteo.update({estado.value: n for estado, n in filas})
    en_riesgo = db.scalar(
        select(func.count()).where(
            Envio.estado.not_in((EstadoEnvio.entregado, EstadoEnvio.devuelto)),
            Envio.fecha_limite_sla < ahora() + timedelta(hours=2),
        )
    )
    entregados = db.scalars(
        select(PruebaEntrega.entregado_en <= Envio.fecha_limite_sla)
        .select_from(PruebaEntrega)
        .join(Envio, Envio.id == PruebaEntrega.envio_id)
    ).all()
    a_tiempo = round(100 * sum(entregados) / len(entregados), 1) if entregados else None
    return {"total": sum(conteo.values()), "por_estado": conteo, "en_riesgo_sla": en_riesgo,
            "cumplimiento_sla_pct": a_tiempo}


@app.get("/api/v1/envios/seguimiento/{codigo}", response_model=SeguimientoOut, tags=["seguimiento público"])
def seguimiento(codigo: str, db: Db):
    envio = db.scalar(select(Envio).where(Envio.codigo == codigo.upper()))
    if not envio:
        raise error(404, "envio_no_encontrado", "No existe un envío con ese código")
    return envio


@app.get("/api/v1/envios/{envio_id}", response_model=EnvioDetalleOut, tags=["envíos"])
def ver(envio_id: uuid.UUID, db: Db):
    return obtener(db, envio_id)


@app.get("/api/v1/envios/{envio_id}/historial", tags=["envíos"])
def historial(envio_id: uuid.UUID, db: Db):
    return [
        {"tipo_evento": e.tipo_evento, "ocurrido_en": e.ocurrido_en, "notas": e.notas}
        for e in obtener(db, envio_id).eventos
    ]


# ---------------------------------------------------------------- comandos


@app.post("/api/v1/envios", response_model=EnvioOut, status_code=201, tags=["envíos"])
def crear(
    datos: EnvioIn,
    db: Db,
    tareas: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(max_length=64)] = None,
    _=requiere_rol("operador"),
):
    """Guarda el envío y su evento de outbox en la MISMA transacción y responde 201 de inmediato.

    La asignación de vehículo ocurre después, en segundo plano: el operador no espera.
    Un reintento con la misma cabecera Idempotency-Key devuelve el envío original (200), sin duplicarlo.
    """
    if idempotency_key:
        existente = db.scalar(select(Envio).where(Envio.idempotency_key == idempotency_key))
        if existente:
            return JSONResponse(EnvioOut.model_validate(existente).model_dump(mode="json"), status_code=200)
    envio = Envio(**datos.model_dump(), codigo=generar_codigo(db), idempotency_key=idempotency_key)
    db.add(envio)
    db.flush()
    registrar(db, envio, TipoEventoEnvio.creado, f"{envio.origen} → {envio.destino}")
    registrar_evento(db, "shipment.created", envio.id,
                     datos_evento(envio, peso_kg=datos.peso_kg, volumen_m3=datos.volumen_m3,
                                  requiere_refrigeracion=datos.requiere_refrigeracion, es_hazmat=datos.es_hazmat))
    db.commit()
    tareas.add_task(asignar_envio, envio.id)
    return envio


@app.post("/api/v1/envios/{envio_id}/asignar", response_model=EnvioOut, tags=["envíos"])
def asignar_manual(envio_id: uuid.UUID, db: Db, _=requiere_rol("operador")):
    exigir_estado(obtener(db, envio_id), EstadoEnvio.pendiente, EstadoEnvio.retrasado)
    db.rollback()
    asignar_envio(envio_id)
    db.expire_all()
    return obtener(db, envio_id)


@app.post("/api/v1/envios/{envio_id}/incidencia", response_model=EnvioOut, tags=["envíos"])
def incidencia(envio_id: uuid.UUID, datos: IncidenciaIn, db: Db, _=requiere_rol("operador", "conductor")):
    """Paso 1-2 de la saga: se registra el hecho y se publica shipment.incident."""
    envio = obtener(db, envio_id, bloquear=True)
    exigir_estado(envio, EstadoEnvio.en_transito)
    envio.estado = EstadoEnvio.con_incidencia
    registrar(db, envio, TipoEventoEnvio.incidencia, f"{datos.tipo}: {datos.descripcion}")
    registrar_evento(db, "shipment.incident", envio.id,
                     datos_evento(envio, tipo=datos.tipo, descripcion=datos.descripcion, lat=datos.lat, lon=datos.lon))
    db.commit()
    return envio


@app.post("/api/v1/envios/{envio_id}/reanudar", response_model=EnvioOut, tags=["envíos"])
def reanudar(envio_id: uuid.UUID, datos: NotaIn, db: Db, _=requiere_rol("operador", "conductor")):
    envio = obtener(db, envio_id, bloquear=True)
    exigir_estado(envio, EstadoEnvio.con_incidencia)
    envio.estado = EstadoEnvio.en_transito
    registrar(db, envio, TipoEventoEnvio.reanudado, datos.notas or "Incidencia resuelta")
    db.commit()
    return envio


@app.post("/api/v1/envios/{envio_id}/prueba-entrega", response_model=EnvioDetalleOut, tags=["envíos"])
def prueba_entrega(
    envio_id: uuid.UUID, datos: PruebaEntregaIn, db: Db, _=requiere_rol("operador", "conductor")
):
    envio = obtener(db, envio_id, bloquear=True)
    exigir_estado(envio, EstadoEnvio.en_transito, EstadoEnvio.con_incidencia)
    envio.estado = EstadoEnvio.entregado
    db.add(PruebaEntrega(envio_id=envio.id, **datos.model_dump()))
    registrar(db, envio, TipoEventoEnvio.entregado, f"Recibido por {datos.nombre_receptor}")
    registrar_evento(db, "shipment.delivered", envio.id,
                     datos_evento(envio, receptor=datos.nombre_receptor,
                                  a_tiempo=ahora() <= envio.fecha_limite_sla))
    db.commit()
    db.expire_all()
    return obtener(db, envio_id)


@app.post("/api/v1/envios/{envio_id}/devolucion", response_model=EnvioOut, tags=["envíos"])
def devolucion(envio_id: uuid.UUID, datos: NotaIn, db: Db, _=requiere_rol("operador")):
    envio = obtener(db, envio_id, bloquear=True)
    exigir_estado(envio, EstadoEnvio.en_transito, EstadoEnvio.con_incidencia, EstadoEnvio.retrasado)
    envio.estado = EstadoEnvio.devuelto
    registrar(db, envio, TipoEventoEnvio.devuelto, datos.notas or "Devuelto al remitente")
    registrar_evento(db, "shipment.returned", envio.id, datos_evento(envio, motivo=datos.notas))
    db.commit()
    return envio
