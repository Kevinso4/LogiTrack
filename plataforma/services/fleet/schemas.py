import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import EstadoVehiculo, TipoVehiculo


class VehiculoIn(BaseModel):
    placa: str = Field(min_length=5, max_length=10, examples=["MTR-123"])
    tipo: TipoVehiculo
    marca: str = Field(min_length=2, max_length=60)
    capacidad_kg: float = Field(gt=0, le=60000)
    capacidad_m3: float = Field(gt=0, le=150)
    anio: int = Field(ge=1990, le=2100)
    vencimiento_seguro: date
    refrigerado: bool = False
    certificado_hazmat: bool = False
    zona: str = Field(min_length=2, max_length=60)

    @field_validator("placa")
    @classmethod
    def placa_valida(cls, v: str) -> str:
        v = v.strip().upper()
        if not all(c.isalnum() or c == "-" for c in v):
            raise ValueError("La placa solo admite letras, números y guion")
        return v


class ConductorResumen(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nombre: str


class VehiculoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    placa: str
    tipo: TipoVehiculo
    marca: str
    capacidad_kg: float
    capacidad_m3: float
    anio: int
    vencimiento_seguro: date
    estado: EstadoVehiculo
    refrigerado: bool
    certificado_hazmat: bool
    zona: str
    actualizado_en: datetime
    conductor: ConductorResumen | None = None


class CambioEstadoIn(BaseModel):
    estado: EstadoVehiculo
    motivo: str = Field(default="Cambio manual desde el panel", max_length=200)


class ConductorIn(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    numero_licencia: str = Field(min_length=4, max_length=30)
    telefono: str | None = Field(default=None, max_length=20)
    certificacion_hazmat: bool = False
    categorias: list[str] = Field(default_factory=lambda: ["C2"])


class ConductorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    nombre: str
    numero_licencia: str
    telefono: str | None
    certificacion_hazmat: bool
    horas_conducidas_semana: float
    categorias: list[str]
    vehiculo_placa: str | None = None

    @field_validator("categorias", mode="before")
    @classmethod
    def a_texto(cls, v):
        return [c if isinstance(c, str) else c.categoria for c in v]


class AsignacionIn(BaseModel):
    vehiculo_id: uuid.UUID
    conductor_id: uuid.UUID
