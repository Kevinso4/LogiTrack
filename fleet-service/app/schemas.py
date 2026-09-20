"""Contratos de entrada/salida (segregación de interfaces, sección 1.4).

Ningún consumidor recibe campos que no usa: Routing pide disponibilidad y
recibe lo justo para decidir; la ficha completa es otro endpoint.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dominio import EstadoVehiculo, TipoVehiculo


# --------------------------------------------------------------------------
# Vehículos
# --------------------------------------------------------------------------
class VehiculoCrear(BaseModel):
    plate: str = Field(min_length=5, max_length=20, examples=["SVK123"])
    type: TipoVehiculo
    capacity_kg: float = Field(gt=0, le=60_000)
    capacity_m3: float = Field(gt=0, le=200)
    year: int = Field(ge=1980, le=2100)
    insurance_expiry: date
    refrigeration_capable: bool = False
    hazmat_certified: bool = False
    zona: str = Field(default="sin_asignar", max_length=60)

    @field_validator("plate")
    @classmethod
    def normalizar_placa(cls, v: str) -> str:
        return v.strip().upper().replace("-", "")


class VehiculoActualizar(BaseModel):
    capacity_kg: Optional[float] = Field(default=None, gt=0, le=60_000)
    capacity_m3: Optional[float] = Field(default=None, gt=0, le=200)
    insurance_expiry: Optional[date] = None
    refrigeration_capable: Optional[bool] = None
    hazmat_certified: Optional[bool] = None
    zona: Optional[str] = Field(default=None, max_length=60)


class CambioEstado(BaseModel):
    estado: EstadoVehiculo
    motivo: Optional[str] = Field(default=None, max_length=500)


class VehiculoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plate: str
    type: str
    capacity_kg: float
    capacity_m3: float
    year: int
    insurance_expiry: date
    status: str
    motivo_estado: Optional[str] = None
    refrigeration_capable: bool
    hazmat_certified: bool
    zona: str
    actualizado_en: datetime


class VehiculoDisponibleOut(BaseModel):
    """Contrato delgado que consume Routing Service."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    plate: str
    type: str
    capacity_kg: float
    capacity_m3: float
    zona: str
    refrigeration_capable: bool
    hazmat_certified: bool


class PaginaVehiculos(BaseModel):
    total: int
    items: List[VehiculoOut]


# --------------------------------------------------------------------------
# Conductores
# --------------------------------------------------------------------------
class ConductorCrear(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    license_number: str = Field(min_length=5, max_length=40)
    license_categories: List[str] = Field(default_factory=list, examples=[["C2", "C3"]])
    license_expiry: date
    hazmat_certification: bool = False
    refrigerated_certification: bool = False
    vehicle_id: Optional[str] = None
    hours_driven_week: float = Field(default=0.0, ge=0, le=168)


class ConductorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    license_number: str
    license_categories: List[str]
    license_expiry: date
    hazmat_certification: bool
    refrigerated_certification: bool
    vehicle_id: Optional[str]
    hours_driven_week: float
    activo: bool


class DisponibilidadConductor(BaseModel):
    conductor_id: str
    disponible: bool
    horas_conducidas_semana: float
    horas_restantes: float
    licencia_vigente: bool
    motivos: List[str] = Field(default_factory=list)


class AsignarVehiculo(BaseModel):
    vehicle_id: Optional[str] = None


class RegistrarHoras(BaseModel):
    horas: float = Field(gt=0, le=24)


# --------------------------------------------------------------------------
# Salud
# --------------------------------------------------------------------------
class Salud(BaseModel):
    estado: str
    servicio: str
    version: str
    dependencias: dict = Field(default_factory=dict)
