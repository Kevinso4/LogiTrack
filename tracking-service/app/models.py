"""Modelo de datos de tracking_db.

`telemetry` es una hypertable de TimescaleDB particionada por `time` en
chunks de 7 días (sección 4). La clave primaria es (vehicle_id, time): incluye
la columna de partición —requisito de Timescale— y de paso hace la ingesta
idempotente, porque una lectura reenviada por el dispositivo choca con la
misma clave y se descarta con ON CONFLICT DO NOTHING.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

JSONPortable = JSON().with_variant(JSONB(), "postgresql")


def nuevo_id() -> str:
    return str(uuid.uuid4())


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Telemetry(Base):
    __tablename__ = "telemetry"

    vehicle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    device_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fabricante: Mapped[str] = mapped_column(String(40), default="generico")

    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engine_temp_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fuel_level_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    odometer_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    engine_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    obd2_codes: Mapped[list] = mapped_column(JSONPortable, default=list)

    ingestado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    __table_args__ = (
        # Consulta típica: "recorrido del vehículo X entre dos fechas".
        Index("ix_telemetry_vehiculo_tiempo", "vehicle_id", "time"),
        Index("ix_telemetry_time", "time"),
    )


class OutboxEvent(Base):
    """Outbox solo para `telemetry.aggregated`.

    `telemetry.raw` no tiene consumidores (matriz de eventos, sección 3): es
    persistencia histórica, así que se publica directo para no duplicar la
    escritura del servicio de mayor caudal del sistema. El agregado, en
    cambio, sí lo consumen Routing y Maintenance, y por eso va con garantía
    transaccional.
    """

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=nuevo_id)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSONPortable)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
