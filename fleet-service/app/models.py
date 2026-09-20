"""Modelo de datos de fleet_db (sección 4 del documento).

Tablas de negocio: `vehicles`, `drivers`.
Tablas de infraestructura: `outbox_events` (patrón Outbox) y
`processed_events` (idempotencia del consumidor).
"""

import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.dominio import EstadoVehiculo

# JSONB en PostgreSQL, JSON en SQLite (tests). Mismo código, distinto dialecto.
JSONPortable = JSON().with_variant(JSONB(), "postgresql")


def nuevo_id() -> str:
    return str(uuid.uuid4())


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    plate: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    capacity_kg: Mapped[float] = mapped_column(Float)
    capacity_m3: Mapped[float] = mapped_column(Float)
    year: Mapped[int] = mapped_column(Integer)
    insurance_expiry: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default=EstadoVehiculo.ACTIVO.value, index=True)
    motivo_estado: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refrigeration_capable: Mapped[bool] = mapped_column(Boolean, default=False)
    hazmat_certified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Zona geográfica actual: la consulta de disponibilidad de Routing filtra por ella.
    zona: Mapped[str] = mapped_column(String(60), index=True, default="sin_asignar")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=ahora, onupdate=ahora
    )

    drivers: Mapped[List["Driver"]] = relationship(back_populates="vehicle")

    __table_args__ = (Index("ix_vehicles_disponibilidad", "status", "type", "zona"),)


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    name: Mapped[str] = mapped_column(String(120))
    license_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # C1, C2, C3 (Colombia) — lista de categorías habilitadas.
    license_categories: Mapped[list] = mapped_column(JSONPortable, default=list)
    license_expiry: Mapped[date] = mapped_column(Date)
    hazmat_certification: Mapped[bool] = mapped_column(Boolean, default=False)
    refrigerated_certification: Mapped[bool] = mapped_column(Boolean, default=False)
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("vehicles.id"), nullable=True, index=True
    )
    hours_driven_week: Mapped[float] = mapped_column(Float, default=0.0)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=ahora, onupdate=ahora
    )

    vehicle: Mapped[Optional[Vehicle]] = relationship(back_populates="drivers")


class OutboxEvent(Base):
    """Patrón Outbox (sección 1.5).

    El cambio de estado y la fila del evento se escriben en la MISMA
    transacción. Un relay en segundo plano es el único que habla con RabbitMQ,
    así que o se guardan los dos o no se guarda ninguno.
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


class ProcessedEvent(Base):
    """Idempotencia: un mensaje reentregado no se aplica dos veces (sección 1.5)."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80))
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
