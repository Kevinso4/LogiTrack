import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db import Base, ahora


def _enum(py_enum, nombre):
    return Enum(py_enum, name=nombre, values_callable=lambda e: [m.value for m in e])


class TipoVehiculo(str, enum.Enum):
    furgon = "furgon"
    camion = "camion"
    tractomula = "tractomula"
    van = "van"


class EstadoVehiculo(str, enum.Enum):
    activo = "activo"
    en_transito = "en_transito"
    en_mantenimiento = "en_mantenimiento"
    fuera_de_servicio = "fuera_de_servicio"


class Vehiculo(Base):
    __tablename__ = "vehiculos"
    __table_args__ = (
        CheckConstraint("capacidad_kg > 0", name="ck_capacidad_kg"),
        CheckConstraint("capacidad_m3 > 0", name="ck_capacidad_m3"),
        Index("idx_veh_estado_tipo", "estado", "tipo", "refrigerado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    placa: Mapped[str] = mapped_column(String(10), unique=True)
    tipo: Mapped[TipoVehiculo] = mapped_column(_enum(TipoVehiculo, "tipo_vehiculo"))
    marca: Mapped[str] = mapped_column(String(60))
    capacidad_kg: Mapped[float] = mapped_column(Numeric(10, 2))
    capacidad_m3: Mapped[float] = mapped_column(Numeric(8, 2))
    anio: Mapped[int] = mapped_column(SmallInteger)
    vencimiento_seguro: Mapped[date] = mapped_column(Date)
    estado: Mapped[EstadoVehiculo] = mapped_column(
        _enum(EstadoVehiculo, "estado_vehiculo"), default=EstadoVehiculo.activo
    )
    refrigerado: Mapped[bool] = mapped_column(Boolean, default=False)
    certificado_hazmat: Mapped[bool] = mapped_column(Boolean, default=False)
    zona: Mapped[str] = mapped_column(String(60), index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora, onupdate=ahora)

    asignaciones: Mapped[list["Asignacion"]] = relationship(back_populates="vehiculo")


class Conductor(Base):
    __tablename__ = "conductores"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120))
    numero_licencia: Mapped[str] = mapped_column(String(30), unique=True)
    telefono: Mapped[str | None] = mapped_column(String(20), nullable=True)
    certificacion_hazmat: Mapped[bool] = mapped_column(Boolean, default=False)
    horas_conducidas_semana: Mapped[float] = mapped_column(Numeric(5, 2), default=0)

    categorias: Mapped[list["ConductorCategoria"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ConductorCategoria(Base):
    __tablename__ = "conductor_categorias"

    conductor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conductores.id"), primary_key=True)
    categoria: Mapped[str] = mapped_column(String(4), primary_key=True)


class Asignacion(Base):
    __tablename__ = "asignaciones"
    __table_args__ = (Index("idx_asig_vigente", "vehiculo_id", "hasta"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vehiculos.id"))
    conductor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conductores.id"))
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vehiculo: Mapped[Vehiculo] = relationship(back_populates="asignaciones")
    conductor: Mapped[Conductor] = relationship(lazy="joined")
