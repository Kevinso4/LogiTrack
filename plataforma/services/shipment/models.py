import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base, ahora


def _enum(py_enum, nombre):
    return Enum(py_enum, name=nombre, values_callable=lambda e: [m.value for m in e])


class EstadoEnvio(str, enum.Enum):
    pendiente = "pendiente"
    en_transito = "en_transito"
    con_incidencia = "con_incidencia"
    retrasado = "retrasado"
    entregado = "entregado"
    devuelto = "devuelto"


class TipoEventoEnvio(str, enum.Enum):
    creado = "creado"
    asignado = "asignado"
    reasignado = "reasignado"
    incidencia = "incidencia"
    retrasado = "retrasado"
    reanudado = "reanudado"
    entregado = "entregado"
    devuelto = "devuelto"


class Envio(Base):
    __tablename__ = "envios"
    __table_args__ = (
        CheckConstraint("peso_kg > 0", name="ck_peso"),
        CheckConstraint("volumen_m3 > 0", name="ck_volumen"),
        Index("idx_env_estado_sla", "estado", "fecha_limite_sla"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    codigo: Mapped[str] = mapped_column(String(12), unique=True)  # código público de seguimiento
    cliente: Mapped[str] = mapped_column(String(120))
    cliente_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    origen: Mapped[str] = mapped_column(String(200))
    destino: Mapped[str] = mapped_column(String(200))
    origen_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    origen_lon: Mapped[float] = mapped_column(Numeric(9, 6))
    destino_lat: Mapped[float] = mapped_column(Numeric(9, 6))
    destino_lon: Mapped[float] = mapped_column(Numeric(9, 6))
    estado: Mapped[EstadoEnvio] = mapped_column(_enum(EstadoEnvio, "estado_envio"), default=EstadoEnvio.pendiente)
    fecha_limite_sla: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    es_internacional: Mapped[bool] = mapped_column(Boolean, default=False)
    requiere_refrigeracion: Mapped[bool] = mapped_column(Boolean, default=False)
    es_hazmat: Mapped[bool] = mapped_column(Boolean, default=False)
    peso_kg: Mapped[float] = mapped_column(Numeric(10, 2))
    volumen_m3: Mapped[float] = mapped_column(Numeric(8, 2))
    vehiculo_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)  # externo (Fleet)
    vehiculo_placa: Mapped[str | None] = mapped_column(String(10), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)

    eventos: Mapped[list["EventoEnvio"]] = relationship(order_by="EventoEnvio.id", lazy="selectin")
    prueba: Mapped["PruebaEntrega | None"] = relationship(lazy="selectin")


class EventoEnvio(Base):
    """Cadena de custodia: tabla de solo inserción."""

    __tablename__ = "eventos_envio"
    __table_args__ = (Index("idx_ev_envio", "envio_id", "ocurrido_en"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    envio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envios.id"))
    tipo_evento: Mapped[TipoEventoEnvio] = mapped_column(_enum(TipoEventoEnvio, "tipo_evento_envio"))
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)


class PruebaEntrega(Base):
    __tablename__ = "pruebas_entrega"

    envio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("envios.id"), primary_key=True)
    nombre_receptor: Mapped[str] = mapped_column(String(120))
    url_firma: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_foto: Mapped[str | None] = mapped_column(Text, nullable=True)
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    entregado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
