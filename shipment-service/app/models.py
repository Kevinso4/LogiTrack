"""Modelo de datos de shipment_db.

Tablas de negocio: `envios`, `historial_envios` (auditoría de estados) y
`pruebas_entrega`. Tablas de infraestructura: `outbox_events` (patrón Outbox)
y `processed_events` (idempotencia del consumidor).
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
from app.dominio import EstadoEnvio

# JSONB en PostgreSQL, JSON en SQLite (tests). Mismo código, distinto dialecto.
JSONPortable = JSON().with_variant(JSONB(), "postgresql")


def nuevo_id() -> str:
    return str(uuid.uuid4())


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Envio(Base):
    __tablename__ = "envios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    client_id: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    estado: Mapped[str] = mapped_column(
        String(30), default=EstadoEnvio.EN_ALMACEN.value, index=True
    )

    # Contrato del evento: el envío nace como un shipment.created. Routing y
    # Customs consumen ESTA forma, nunca una vista parcial.
    origen: Mapped[dict] = mapped_column(JSONPortable)
    destino: Mapped[dict] = mapped_column(JSONPortable)
    peso_kg: Mapped[float] = mapped_column(Float)
    volumen_m3: Mapped[float] = mapped_column(Float)
    is_international: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    requiere_refrigeracion: Mapped[bool] = mapped_column(Boolean, default=False)
    requiere_hazmat: Mapped[bool] = mapped_column(Boolean, default=False)
    ventana_entrega: Mapped[Optional[dict]] = mapped_column(JSONPortable, nullable=True)

    # Datos de la ruta asignada por Routing (reflexión del evento, sin JOIN).
    ruta_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    vehicle_plate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    eta: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=ahora, onupdate=ahora
    )

    __table_args__ = (Index("ix_envios_estado_cliente", "estado", "client_id"),)


class HistorialEnvio(Base):
    """Auditoría: cada transición de estado deja una huella inmutable."""

    __tablename__ = "historial_envios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shipment_id: Mapped[str] = mapped_column(String(36), ForeignKey("envios.id"), index=True)
    desde: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    hasta: Mapped[str] = mapped_column(String(30))
    motivo: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class PruebaEntrega(Base):
    """Prueba de entrega (POD): quién recibió, cuándo y con qué respaldo."""

    __tablename__ = "pruebas_entrega"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_id)
    shipment_id: Mapped[str] = mapped_column(String(36), ForeignKey("envios.id"), unique=True)
    nombre_recibe: Mapped[str] = mapped_column(String(120))
    documento_recibe: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    firma_foto_url: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    comentario: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class OutboxEvent(Base):
    """Patrón Outbox: el efeo de negocio y el evento salen en el mismo commit."""

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
    """Idempotencia: un mensaje reentregado no se aplica dos veces."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80))
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
