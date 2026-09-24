import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import EstadoEnvio, TipoEventoEnvio


class EnvioIn(BaseModel):
    cliente: str = Field(min_length=2, max_length=120)
    cliente_email: str | None = Field(default=None, max_length=120)
    origen: str = Field(min_length=2, max_length=200)
    destino: str = Field(min_length=2, max_length=200)
    origen_lat: float = Field(ge=-90, le=90)
    origen_lon: float = Field(ge=-180, le=180)
    destino_lat: float = Field(ge=-90, le=90)
    destino_lon: float = Field(ge=-180, le=180)
    fecha_limite_sla: datetime
    es_internacional: bool = False
    requiere_refrigeracion: bool = False
    es_hazmat: bool = False
    peso_kg: float = Field(gt=0, le=40000)
    volumen_m3: float = Field(gt=0, le=120)

    @field_validator("fecha_limite_sla")
    @classmethod
    def en_el_futuro(cls, v: datetime) -> datetime:
        v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if v <= datetime.now(timezone.utc):
            raise ValueError("La fecha límite del SLA debe estar en el futuro")
        return v

    @model_validator(mode="after")
    def origen_distinto(self):
        if self.origen.strip().lower() == self.destino.strip().lower():
            raise ValueError("El origen y el destino deben ser distintos")
        return self


class EventoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tipo_evento: TipoEventoEnvio
    ocurrido_en: datetime
    notas: str | None


class PruebaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    nombre_receptor: str
    url_firma: str | None
    url_foto: str | None
    lat: float | None
    lon: float | None
    entregado_en: datetime


class EnvioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    codigo: str
    cliente: str
    cliente_email: str | None
    origen: str
    destino: str
    origen_lat: float
    origen_lon: float
    destino_lat: float
    destino_lon: float
    estado: EstadoEnvio
    fecha_limite_sla: datetime
    es_internacional: bool
    requiere_refrigeracion: bool
    es_hazmat: bool
    peso_kg: float
    volumen_m3: float
    vehiculo_id: uuid.UUID | None
    vehiculo_placa: str | None
    creado_en: datetime
    actualizado_en: datetime


class EnvioDetalleOut(EnvioOut):
    eventos: list[EventoOut]
    prueba: PruebaOut | None


class EventoPublicoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tipo_evento: TipoEventoEnvio
    ocurrido_en: datetime


class SeguimientoOut(BaseModel):
    """Vista pública (sin sesión): sin datos del cliente, ni placas, ni notas internas."""

    model_config = ConfigDict(from_attributes=True)
    codigo: str
    origen: str
    destino: str
    estado: EstadoEnvio
    fecha_limite_sla: datetime
    eventos: list[EventoPublicoOut]


class IncidenciaIn(BaseModel):
    tipo: Literal["averia", "accidente", "retraso_trafico", "clima", "otro"]
    descripcion: str = Field(min_length=3, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class PruebaEntregaIn(BaseModel):
    nombre_receptor: str = Field(min_length=2, max_length=120)
    url_firma: str | None = Field(default=None, max_length=500)
    url_foto: str | None = Field(default=None, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class NotaIn(BaseModel):
    notas: str = Field(default="", max_length=500)
