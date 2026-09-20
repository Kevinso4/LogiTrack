"""Agregación por ventanas y publicación de `telemetry.aggregated`.

El evento agregado es el que consumen Routing (para detectar desvíos) y
Maintenance (para umbrales de motor y kilometraje). Va por el outbox: si el
broker está caído, sale cuando vuelve, sin perderse.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.events.outbox import registrar_evento
from app.models import Telemetry
from app.normalizacion import distancia_km
from app.observabilidad import log, vehiculos_agregados
from app.schemas import AgregadoOut

logger = logging.getLogger(__name__)

EVENTO_AGREGADO = "telemetry.aggregated"
UMBRAL_DETENIDO_KM = 0.05


def _agregar_vehiculo(
    vehicle_id: str,
    filas: Sequence[Telemetry],
    inicio: datetime,
    fin: datetime,
) -> AgregadoOut:
    velocidades = [f.speed_kmh for f in filas if f.speed_kmh is not None]
    temperaturas = [f.engine_temp_c for f in filas if f.engine_temp_c is not None]
    odometros = [f.odometer_km for f in filas if f.odometer_km is not None]
    horas = [f.engine_hours for f in filas if f.engine_hours is not None]

    total_km = 0.0
    for anterior, actual in zip(filas, filas[1:]):
        total_km += distancia_km(anterior.lat, anterior.lon, actual.lat, actual.lon)

    # Si hay odómetro fiable, manda el odómetro sobre el cálculo geométrico.
    if len(odometros) >= 2:
        delta_odometro = odometros[-1] - odometros[0]
        if delta_odometro >= 0:
            total_km = delta_odometro

    codigos = sorted({c for f in filas for c in (f.obd2_codes or [])})
    ultima = filas[-1]

    return AgregadoOut(
        vehicle_id=vehicle_id,
        ventana_inicio=inicio,
        ventana_fin=fin,
        lecturas=len(filas),
        velocidad_promedio_kmh=(
            round(sum(velocidades) / len(velocidades), 2) if velocidades else None
        ),
        velocidad_maxima_kmh=max(velocidades) if velocidades else None,
        temperatura_motor_max_c=max(temperaturas) if temperaturas else None,
        combustible_pct=ultima.fuel_level_pct,
        odometro_km=odometros[-1] if odometros else None,
        distancia_km=round(total_km, 4),
        horas_motor=horas[-1] if horas else None,
        codigos_obd2=codigos,
        ultima_posicion={"lat": ultima.lat, "lon": ultima.lon},
        detenido=total_km < UMBRAL_DETENIDO_KM and not any(v > 1 for v in velocidades),
    )


class Agregador:
    def __init__(self, ventana_segundos: Optional[int] = None) -> None:
        settings = get_settings()
        self._ventana = ventana_segundos or settings.ventana_agregacion_segundos
        self._tarea: Optional[asyncio.Task] = None
        self._parar = asyncio.Event()

    async def ejecutar_ventana(
        self, fin: Optional[datetime] = None, inicio: Optional[datetime] = None
    ) -> List[AgregadoOut]:
        """Agrega la ventana [fin - ventana, fin) y encola un evento por vehículo."""
        fin = fin or datetime.now(timezone.utc)
        inicio = inicio or fin - timedelta(seconds=self._ventana)

        async with SessionLocal() as session:
            filas = (
                (
                    await session.execute(
                        select(Telemetry)
                        .where(Telemetry.time >= inicio, Telemetry.time < fin)
                        .order_by(Telemetry.vehicle_id, Telemetry.time)
                    )
                )
                .scalars()
                .all()
            )

            por_vehiculo: Dict[str, List[Telemetry]] = {}
            for fila in filas:
                por_vehiculo.setdefault(fila.vehicle_id, []).append(fila)

            agregados: List[AgregadoOut] = []
            for vehicle_id, lecturas in por_vehiculo.items():
                agregado = _agregar_vehiculo(vehicle_id, lecturas, inicio, fin)
                agregados.append(agregado)
                registrar_evento(session, EVENTO_AGREGADO, agregado.model_dump(mode="json"))

            if agregados:
                await session.commit()

        vehiculos_agregados.set(len(agregados))
        if agregados:
            log(
                logger,
                logging.INFO,
                "ventana.agregada",
                vehiculos=len(agregados),
                lecturas=len(filas),
                ventana_s=self._ventana,
            )
        return agregados

    def iniciar(self) -> None:
        self._parar.clear()
        self._tarea = asyncio.create_task(self._bucle(), name="agregador")

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self) -> None:
        while not self._parar.is_set():
            await asyncio.sleep(self._ventana)
            try:
                await self.ejecutar_ventana()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("agregador.error")
