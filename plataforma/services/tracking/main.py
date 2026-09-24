"""Tracking Ingestion Service — recibe, valida y normaliza telemetría; la publica sin analizarla.

Publica:  telemetry.raw (resumen del lote), telemetry.aggregated (un agregado por vehículo y lote)
Consume:  nada
Los dispositivos se autentican con una API key (cabecera X-Device-Key); solo se guarda su SHA-256.
"""
import hashlib
import logging
import secrets
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from common.app import crear_app
from common.db import SessionLocal, ahora, engine, get_db
from common.errores import error
from common.seguridad import requiere_rol

from .models import Dispositivo, Posicion

log = logging.getLogger("tracking")
Db = Annotated[Session, Depends(get_db)]


def preparar_timescale() -> None:
    """Convierte posiciones en hypertable (idempotente) si la extensión está disponible."""
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            conn.execute(
                text(
                    "SELECT create_hypertable('posiciones', 'registrado_en', "
                    "chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE, migrate_data => TRUE)"
                )
            )
        log.info("Hypertable 'posiciones' lista (TimescaleDB)")
    except Exception as exc:
        log.warning("TimescaleDB no disponible, se usa tabla normal: %s", exc)


app = crear_app("tracking", "LogiTrack · Tracking Ingestion Service", al_iniciar=preparar_timescale,
                usa_outbox=False)


# ---------------------------------------------------------------- esquemas


class LecturaIn(BaseModel):
    vehiculo_id: uuid.UUID
    registrado_en: datetime
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    velocidad_kmh: float = Field(ge=0, le=250)
    nivel_combustible: float = Field(ge=0, le=100)
    temperatura_c: float | None = Field(default=None, ge=-40, le=80)
    temperatura_motor_c: float = Field(ge=-40, le=200)
    odometro_km: float = Field(ge=0)
    codigo_obd2: str | None = Field(default=None, max_length=8)

    @field_validator("registrado_en")
    @classmethod
    def con_zona(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    @field_validator("codigo_obd2")
    @classmethod
    def normalizar_obd(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None


class LoteIn(BaseModel):
    lecturas: list[LecturaIn] = Field(min_length=1, max_length=1000)


class DispositivoIn(BaseModel):
    vehiculo_id: uuid.UUID
    fabricante: str = Field(default="Teltonika", max_length=60)


def _hash(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def _redondear(v) -> float | None:
    return None if v is None else round(float(v), 2)


# ---------------------------------------------------------------- dispositivos


@app.post("/api/v1/dispositivos", status_code=201, tags=["dispositivos"])
def registrar_dispositivo(datos: DispositivoIn, db: Db, _=requiere_rol("gestor_flota")):
    """Da de alta (o rota la clave de) el dispositivo de un vehículo. La clave solo se muestra una vez."""
    clave = secrets.token_urlsafe(24)
    disp = db.scalar(select(Dispositivo).where(Dispositivo.vehiculo_id == datos.vehiculo_id))
    if disp:
        disp.api_key_hash = _hash(clave)
        disp.fabricante = datos.fabricante
    else:
        disp = Dispositivo(vehiculo_id=datos.vehiculo_id, fabricante=datos.fabricante, api_key_hash=_hash(clave))
        db.add(disp)
    db.commit()
    return {"dispositivo_id": disp.id, "vehiculo_id": disp.vehiculo_id, "api_key": clave}


# ---------------------------------------------------------------- ingesta


def _guardar_lote(lote: LoteIn, clave: str) -> None:
    vehiculos = {l.vehiculo_id for l in lote.lecturas}
    with SessionLocal() as db:
        disp = {
            d.vehiculo_id: d
            for d in db.scalars(select(Dispositivo).where(Dispositivo.vehiculo_id.in_(vehiculos)))
        }
        h = _hash(clave)
        for vid in vehiculos:
            if vid not in disp or not secrets.compare_digest(disp[vid].api_key_hash, h):
                raise error(401, "dispositivo_no_autorizado", f"Clave inválida para el vehículo {vid}")
        filas = [l.model_dump() for l in lote.lecturas]
        # Reenvíos del dispositivo (modo offline) no duplican lecturas: la PK es (vehiculo, instante).
        db.execute(insert(Posicion).values(filas).on_conflict_do_nothing())
        for vid in vehiculos:
            disp[vid].ultima_lectura = ahora()
        db.commit()


def _agregar(lecturas: list[LecturaIn]) -> list[dict]:
    por_vehiculo: dict[uuid.UUID, list[LecturaIn]] = defaultdict(list)
    for l in lecturas:
        por_vehiculo[l.vehiculo_id].append(l)
    agregados = []
    for vid, ls in por_vehiculo.items():
        ls.sort(key=lambda l: l.registrado_en)
        ultima = ls[-1]
        temps_carga = [l.temperatura_c for l in ls if l.temperatura_c is not None]
        agregados.append(
            {
                "vehiculo_id": str(vid),
                "desde": ls[0].registrado_en.isoformat(),
                "hasta": ultima.registrado_en.isoformat(),
                "lecturas": len(ls),
                "lat": ultima.lat,
                "lon": ultima.lon,
                "velocidad_promedio": round(sum(l.velocidad_kmh for l in ls) / len(ls), 1),
                "velocidad_max": max(l.velocidad_kmh for l in ls),
                "nivel_combustible": ultima.nivel_combustible,
                "temperatura_motor_max": max(l.temperatura_motor_c for l in ls),
                "temperatura_carga_max": max(temps_carga) if temps_carga else None,
                "odometro_km": ultima.odometro_km,
                "codigos_obd2": sorted({l.codigo_obd2 for l in ls if l.codigo_obd2}),
            }
        )
    return agregados


@app.post("/api/v1/telemetria", status_code=202, tags=["telemetría"])
async def ingerir(lote: LoteIn, request: Request, x_device_key: Annotated[str, Header()]):
    """Recibe un lote, lo persiste y publica. Nunca espera a ningún otro servicio."""
    await run_in_threadpool(_guardar_lote, lote, x_device_key)
    bus = request.app.state.bus
    agregados = _agregar(lote.lecturas)
    await bus.publicar("telemetry.raw", {"lecturas": len(lote.lecturas), "vehiculos": len(agregados)})
    for agg in agregados:
        await bus.publicar("telemetry.aggregated", agg)
    return {"aceptadas": len(lote.lecturas)}


# ---------------------------------------------------------------- consultas


def _posicion_dict(p: Posicion) -> dict:
    return {
        "vehiculo_id": p.vehiculo_id,
        "registrado_en": p.registrado_en,
        "lat": float(p.lat),
        "lon": float(p.lon),
        "velocidad_kmh": _redondear(p.velocidad_kmh),
        "nivel_combustible": _redondear(p.nivel_combustible),
        "temperatura_c": _redondear(p.temperatura_c),
        "temperatura_motor_c": _redondear(p.temperatura_motor_c),
        "odometro_km": _redondear(p.odometro_km),
        "codigo_obd2": p.codigo_obd2,
    }


@app.get("/api/v1/telemetria/ultimas", tags=["telemetría"])
def ultimas_posiciones(db: Db):
    """Última posición conocida de cada vehículo (para el mapa en vivo)."""
    sub = (
        select(Posicion.vehiculo_id, func.max(Posicion.registrado_en).label("max_t"))
        .where(Posicion.registrado_en > ahora() - timedelta(days=1))
        .group_by(Posicion.vehiculo_id)
        .subquery()
    )
    filas = db.scalars(
        select(Posicion).join(
            sub, (Posicion.vehiculo_id == sub.c.vehiculo_id) & (Posicion.registrado_en == sub.c.max_t)
        )
    )
    return [_posicion_dict(p) for p in filas]


@app.get("/api/v1/telemetria/estadisticas", tags=["telemetría"])
def estadisticas(db: Db):
    hace_1m = ahora() - timedelta(minutes=1)
    ultimo_minuto = db.scalar(select(func.count()).where(Posicion.registrado_en > hace_1m))
    reportando = db.scalar(
        select(func.count(func.distinct(Posicion.vehiculo_id))).where(Posicion.registrado_en > hace_1m)
    )
    return {
        "lecturas_ultimo_minuto": ultimo_minuto,
        "lecturas_por_segundo": round(ultimo_minuto / 60, 2),
        "vehiculos_reportando": reportando,
    }


@app.get("/api/v1/telemetria/{vehiculo_id}/ultima", tags=["telemetría"])
def ultima(vehiculo_id: uuid.UUID, db: Db):
    p = db.scalar(
        select(Posicion).where(Posicion.vehiculo_id == vehiculo_id).order_by(Posicion.registrado_en.desc()).limit(1)
    )
    if not p:
        raise error(404, "sin_telemetria", "El vehículo aún no ha reportado telemetría")
    return _posicion_dict(p)


@app.get("/api/v1/telemetria/{vehiculo_id}/recorrido", tags=["telemetría"])
def recorrido(
    vehiculo_id: uuid.UUID,
    db: Db,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    limite: int = Query(default=500, ge=1, le=5000),
):
    hasta = hasta or ahora()
    desde = desde or hasta - timedelta(hours=1)
    filas = db.scalars(
        select(Posicion)
        .where(Posicion.vehiculo_id == vehiculo_id, Posicion.registrado_en.between(desde, hasta))
        .order_by(Posicion.registrado_en.desc())
        .limit(limite)
    )
    return list(reversed([_posicion_dict(p) for p in filas]))
