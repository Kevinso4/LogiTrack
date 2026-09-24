import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from common.db import Base, ahora


def _enum(py_enum, nombre):
    return Enum(py_enum, name=nombre, values_callable=lambda e: [m.value for m in e])


class Metrica(str, enum.Enum):
    temperatura_motor = "temperatura_motor"
    nivel_combustible = "nivel_combustible"
    velocidad = "velocidad"
    temperatura_carga = "temperatura_carga"
    codigo_obd2 = "codigo_obd2"


class Operador(str, enum.Enum):
    mayor = "mayor"
    menor = "menor"
    presente = "presente"


METRICA = _enum(Metrica, "metrica")  # un único tipo ENUM compartido por dos tablas


class EstadoAlerta(str, enum.Enum):
    abierta = "abierta"
    cerrada = "cerrada"


class EstadoPrograma(str, enum.Enum):
    programado = "programado"
    completado = "completado"


class Regla(Base):
    __tablename__ = "reglas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120))
    tipo_vehiculo: Mapped[str | None] = mapped_column(String(20), nullable=True)  # None = todos
    metrica: Mapped[Metrica] = mapped_column(METRICA)
    operador: Mapped[Operador] = mapped_column(_enum(Operador, "operador_regla"))
    umbral: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    prioridad: Mapped[int] = mapped_column(SmallInteger, default=2)  # 1 = crítica
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class Alerta(Base):
    __tablename__ = "alertas"
    __table_args__ = (Index("idx_alerta_vehiculo_estado", "vehiculo_id", "estado"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # externo (Fleet)
    regla_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reglas.id"))
    metrica: Mapped[Metrica] = mapped_column(METRICA)
    valor: Mapped[str] = mapped_column(String(40))
    mensaje: Mapped[str] = mapped_column(String(250))
    prioridad: Mapped[int] = mapped_column(SmallInteger)
    estado: Mapped[EstadoAlerta] = mapped_column(_enum(EstadoAlerta, "estado_alerta"), default=EstadoAlerta.abierta)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProgramaMantenimiento(Base):
    __tablename__ = "programas_mantenimiento"
    __table_args__ = (Index("idx_prog_vehiculo_estado", "vehiculo_id", "estado"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # externo (Fleet)
    tipo: Mapped[str] = mapped_column(String(80))
    fecha_prevista: Mapped[date] = mapped_column(Date)
    km_previsto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prioridad: Mapped[int] = mapped_column(SmallInteger, default=2)
    estado: Mapped[EstadoPrograma] = mapped_column(
        _enum(EstadoPrograma, "estado_programa"), default=EstadoPrograma.programado
    )
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


class Intervencion(Base):
    """Historial de intervenciones: tabla de solo inserción (auditoría)."""

    __tablename__ = "intervenciones"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    programa_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("programas_mantenimiento.id"), nullable=True)
    descripcion: Mapped[str] = mapped_column(Text)
    realizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    costo: Mapped[float] = mapped_column(Numeric(12, 2))
    taller: Mapped[str] = mapped_column(String(120))
    km_al_servicio: Mapped[int] = mapped_column(Integer)


class UltimaLectura(Base):
    """Última telemetría agregada conocida por vehículo (proyección local, no la BD de Tracking)."""

    __tablename__ = "ultimas_lecturas"

    vehiculo_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    odometro_km: Mapped[float] = mapped_column(Numeric(10, 1))
    temperatura_motor_max: Mapped[float] = mapped_column(Numeric(5, 2))
    nivel_combustible: Mapped[float] = mapped_column(Numeric(5, 2))
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
