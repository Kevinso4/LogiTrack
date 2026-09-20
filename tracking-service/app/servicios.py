"""Ingesta y consulta de telemetría.

Regla del servicio: recibir, validar, normalizar, guardar y publicar. Nada de
análisis — ni umbrales de motor (Maintenance) ni desvíos de ruta (Routing).
"""

from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.errores import RecursoNoEncontrado
from app.events.base import EventoDominio, PublicadorEventos
from app.models import Telemetry
from app.normalizacion import (
    ErrorNormalizacion,
    LecturaNormalizada,
    distancia_km,
    normalizar,
    obtener_perfil,
)
from app.observabilidad import (
    eventos_fallidos,
    lecturas_aceptadas,
    lecturas_recibidas,
    lecturas_rechazadas,
    log,
    lote_duracion,
    lote_tamano,
)
from app.schemas import LecturaRechazada, LoteTelemetria, RecorridoOut, RespuestaIngesta

logger = logging.getLogger(__name__)

EVENTO_RAW = "telemetry.raw"
EVENTO_AGREGADO = "telemetry.aggregated"


def _insert_ignorando_duplicados(dialecto: str):
    """ON CONFLICT DO NOTHING portable: una lectura reenviada no duplica fila."""
    if dialecto == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return lambda: pg_insert(Telemetry).on_conflict_do_nothing(
            index_elements=["vehicle_id", "time"]
        )
    if dialecto == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return lambda: sqlite_insert(Telemetry).on_conflict_do_nothing(
            index_elements=["vehicle_id", "time"]
        )
    from sqlalchemy import insert

    return lambda: insert(Telemetry)


async def procesar_lote(
    session: AsyncSession,
    lote: LoteTelemetria,
    publicador: Optional[PublicadorEventos] = None,
) -> RespuestaIngesta:
    inicio = _time.perf_counter()
    settings = get_settings()
    perfil = obtener_perfil(lote.fabricante)
    ahora = datetime.now(timezone.utc)

    lecturas_recibidas.labels(perfil.nombre).inc(len(lote.lecturas))
    lote_tamano.observe(len(lote.lecturas))

    validas: List[LecturaNormalizada] = []
    errores: List[LecturaRechazada] = []

    for indice, cruda in enumerate(lote.lecturas):
        try:
            validas.append(
                normalizar(
                    cruda.model_dump(exclude_none=True),
                    perfil,
                    unidades=lote.unidades,
                    device_id=lote.device_id,
                    velocidad_maxima_kmh=settings.velocidad_maxima_kmh,
                    tolerancia_futuro_minutos=settings.tolerancia_futuro_minutos,
                    antiguedad_maxima_horas=settings.antiguedad_maxima_horas,
                    ahora=ahora,
                )
            )
        except ErrorNormalizacion as exc:
            lecturas_rechazadas.labels(exc.motivo).inc()
            errores.append(LecturaRechazada(indice=indice, motivo=exc.motivo, detalle=exc.detalle))

    duplicadas = 0
    if validas:
        # Dentro del mismo lote puede venir la misma (vehículo, instante) repetida.
        unicas = {}
        for lectura in validas:
            unicas[(lectura.vehicle_id, lectura.timestamp)] = lectura
        duplicadas += len(validas) - len(unicas)
        filas = [lectura.como_fila() for lectura in unicas.values()]

        constructor = _insert_ignorando_duplicados(session.bind.dialect.name)
        # RETURNING nos dice exactamente cuántas filas entraron: las que no,
        # eran reenvíos del dispositivo (choque con la PK vehicle_id+time).
        resultado = await session.execute(constructor().returning(Telemetry.vehicle_id), filas)
        insertadas = len(resultado.fetchall())
        await session.commit()

        duplicadas += len(filas) - insertadas
        lecturas_aceptadas.labels(perfil.nombre).inc(insertadas)

        if publicador is not None:
            await _publicar_raw(publicador, list(unicas.values()))

    duracion = _time.perf_counter() - inicio
    lote_duracion.observe(duracion)
    log(
        logger,
        logging.INFO,
        "lote.procesado",
        recibidas=len(lote.lecturas),
        aceptadas=len(validas),
        rechazadas=len(errores),
        fabricante=perfil.nombre,
        duracion_ms=round(duracion * 1000, 2),
    )
    return RespuestaIngesta(
        recibidas=len(lote.lecturas),
        aceptadas=len(validas),
        rechazadas=len(errores),
        duplicadas=duplicadas,
        errores=errores[:50],
        duracion_ms=round(duracion * 1000, 2),
    )


async def _publicar_raw(
    publicador: PublicadorEventos, lecturas: Sequence[LecturaNormalizada]
) -> None:
    """`telemetry.raw`: sin consumidores en caliente, publicación best-effort.

    Si el broker está caído no se pierde el dato (ya está en la hypertable) y
    la ingesta no se bloquea, que es lo que exige la sección 1.1.
    """
    evento = EventoDominio(
        event_type=EVENTO_RAW,
        payload={
            "conteo": len(lecturas),
            "vehiculos": sorted({lec.vehicle_id for lec in lecturas}),
            "lecturas": [
                {
                    "vehicle_id": lec.vehicle_id,
                    "timestamp": lec.timestamp.isoformat(),
                    "lat": lec.lat,
                    "lon": lec.lon,
                    "velocidad_kmh": lec.velocidad_kmh,
                    "temperatura_motor_c": lec.temperatura_motor_c,
                    "combustible_pct": lec.combustible_pct,
                    "odometro_km": lec.odometro_km,
                    "horas_motor": lec.horas_motor,
                    "codigos_obd2": lec.codigos_obd2,
                }
                for lec in lecturas
            ],
        },
    )
    try:
        await publicador.publicar(evento)
    except Exception as exc:
        eventos_fallidos.labels(EVENTO_RAW).inc()
        log(logger, logging.WARNING, "telemetry_raw.no_publicado", error=str(exc))


# --------------------------------------------------------------------------
# Consultas
# --------------------------------------------------------------------------
async def ultima_lectura(session: AsyncSession, vehicle_id: str) -> Telemetry:
    lectura = await session.scalar(
        select(Telemetry)
        .where(Telemetry.vehicle_id == vehicle_id)
        .order_by(Telemetry.time.desc())
        .limit(1)
    )
    if lectura is None:
        raise RecursoNoEncontrado(f"Sin telemetría para el vehículo {vehicle_id}")
    return lectura


async def recorrido(
    session: AsyncSession,
    vehicle_id: str,
    desde: Optional[datetime] = None,
    hasta: Optional[datetime] = None,
    limite: int = 5000,
) -> RecorridoOut:
    hasta = hasta or datetime.now(timezone.utc)
    desde = desde or hasta - timedelta(hours=24)

    filas = (
        (
            await session.execute(
                select(Telemetry)
                .where(
                    Telemetry.vehicle_id == vehicle_id,
                    Telemetry.time >= desde,
                    Telemetry.time <= hasta,
                )
                .order_by(Telemetry.time)
                .limit(limite)
            )
        )
        .scalars()
        .all()
    )

    total_km, velocidades = _metricas_de_recorrido(filas)
    return RecorridoOut(
        vehicle_id=vehicle_id,
        desde=desde,
        hasta=hasta,
        lecturas=len(filas),
        distancia_km=round(total_km, 3),
        velocidad_promedio_kmh=(
            round(sum(velocidades) / len(velocidades), 2) if velocidades else None
        ),
        velocidad_maxima_kmh=max(velocidades) if velocidades else None,
        puntos=filas,
    )


def _metricas_de_recorrido(filas: Sequence[Telemetry]) -> Tuple[float, List[float]]:
    total_km = 0.0
    velocidades: List[float] = []
    anterior: Optional[Telemetry] = None
    for fila in filas:
        if fila.speed_kmh is not None:
            velocidades.append(fila.speed_kmh)
        if anterior is not None:
            total_km += distancia_km(anterior.lat, anterior.lon, fila.lat, fila.lon)
        anterior = fila
    return total_km, velocidades
