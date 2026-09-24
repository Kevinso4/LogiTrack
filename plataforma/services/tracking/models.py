import uuid
from datetime import datetime

from sqlalchemy import CHAR, DateTime, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base, ahora


class Posicion(Base):
    """Hypertable de TimescaleDB particionada por registrado_en (fragmentos de 7 días)."""

    __tablename__ = "posiciones"

    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    registrado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    lat: Mapped[float] = mapped_column(Numeric(9, 6))
    lon: Mapped[float] = mapped_column(Numeric(9, 6))
    velocidad_kmh: Mapped[float] = mapped_column(Numeric(5, 2))
    nivel_combustible: Mapped[float] = mapped_column(Numeric(5, 2))
    temperatura_c: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    temperatura_motor_c: Mapped[float] = mapped_column(Numeric(5, 2))
    odometro_km: Mapped[float] = mapped_column(Numeric(10, 1))
    codigo_obd2: Mapped[str | None] = mapped_column(String(8), nullable=True)


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)  # externo (Fleet)
    fabricante: Mapped[str] = mapped_column(String(60))
    api_key_hash: Mapped[str] = mapped_column(CHAR(64))  # SHA-256, nunca la clave
    ultima_lectura: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
