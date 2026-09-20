"""Modelo de datos de routing_db (sección 4 del documento).

Tablas de negocio: `rutas`, `paradas`, `intentos_asignacion` (traza de la saga).
Tablas de infraestructura: `outbox_events` (patrón Outbox) y
`processed_events` (idempotencia del consumidor).
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.dominio import EstadoRuta

# JSONB en PostgreSQL, JSON en SQLite (tests). Mismo código, distinto dialecto.
JSONPortable = JSON().with_variant(JSONB(), "postgresql")


def nuevo_id() -> str:
    return str(uuid.uuid4())


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Ruta(Base):
    __tablename__ = "rutas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    vehicle_plate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    estado: Mapped[str] = mapped_column(String(30), default=EstadoRuta.PENDIENTE.value, index=True)

    # Demanda copiada del contrato de shipment.created: el recálculo no vuelve
    # a preguntar a Shipment (sin JOIN entre dominios, sección 5a).
    origen: Mapped[dict] = mapped_column(JSONPortable)
    destino: Mapped[dict] = mapped_column(JSONPortable)
    peso_kg: Mapped[float] = mapped_column(Float)
    volumen_m3: Mapped[float] = mapped_column(Float)
    requiere_refrigeracion: Mapped[bool] = mapped_column(Boolean, default=False)
    requiere_hazmat: Mapped[bool] = mapped_column(Boolean, default=False)

    distancia_km: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duracion_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    eta_actual: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # "calculado" (proveedor de mapas) o "estimado" (sin tercero, o tras fallo).
    tipo_calculo: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intentos_recalculo: Mapped[int] = mapped_column(Integer, default=0)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=ahora, onupdate=ahora
    )

    __table_args__ = (Index("ix_rutas_activas_vehiculo", "estado", "vehicle_id"),)


class Parada(Base):
    __tablename__ = "paradas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    ruta_id: Mapped[str] = mapped_column(String(36), ForeignKey("rutas.id"), index=True)
    orden: Mapped[int] = mapped_column(Integer)
    direccion: Mapped[str] = mapped_column(String(200))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    ventana_desde: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ventana_hasta: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    eta_llegada: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class IntentoAsignacion(Base):
    """Traza de la saga: por qué y con qué resultado se (re)asignó una ruta."""

    __tablename__ = "intentos_asignacion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ruta_id: Mapped[str] = mapped_column(String(36), ForeignKey("rutas.id"), index=True)
    shipment_id: Mapped[str] = mapped_column(String(36), index=True)
    causa: Mapped[str] = mapped_column(String(50))
    vehicle_anterior: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    fallido: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class OutboxEvent(Base):
    """Patrón Outbox (sección 5b). El effecto y la fila del evento se escriben
    en la misma transacción; un relay en segundo plano es el único que publica."""

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


class ProcessedEvent(Base):
    """Idempotencia: un mensaje reentregado no se aplica dos veces (sección 5c)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80))
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
