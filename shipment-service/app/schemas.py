"""Contratos de entrada/salida del Shipment Service (ISP, sección 5e).

Los contratos de eventos se escriben en inglés (igual que en el bus, sección 3
del documento) y son la única forma en que otro servicio habla con el envío.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PuntoGps(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    direccion: str = Field(min_length=3, max_length=200)


class VentanaEntrega(BaseModel):
    desde: datetime
    hasta: datetime


# --------------------------------------------------------------------------
# Creación de envío (API REST interna/del equipo de operaciones).
# --------------------------------------------------------------------------
class EnvioRequest(BaseModel):
    client_id: Optional[str] = None
    origen: PuntoGps
    destino: PuntoGps
    peso_kg: float = Field(gt=0)
    volumen_m3: float = Field(ge=0)
    is_international: bool = False
    sla_deadline: Optional[datetime] = None
    requiere_refrigeracion: bool = False
    requiere_hazmat: bool = False
    ventana_entrega: Optional[VentanaEntrega] = None


# --------------------------------------------------------------------------
# Contratos de eventos consumidos (Routing y Customs).
# --------------------------------------------------------------------------
class RouteAssignedPayload(BaseModel):
    ruta_id: str
    shipment_id: str
    vehicle_id: Optional[str] = None
    vehicle_plate: Optional[str] = None
    eta: Optional[datetime] = None
    distancia_km: Optional[float] = None
    duracion_min: Optional[float] = None
    tipo_calculo: Optional[str] = None
    motivo: Optional[str] = None


class RouteRecalculatedPayload(RouteAssignedPayload):
    pass


class RouteUnassignablePayload(BaseModel):
    ruta_id: str
    shipment_id: str
    motivo: Optional[str] = None
    causa: Optional[str] = None


class CustomsHeldPayload(BaseModel):
    shipment_id: str
    motivo: Optional[str] = None
    autogenerado: Optional[bool] = None


class CustomsClearedPayload(BaseModel):
    shipment_id: str
    motivo: Optional[str] = None


# --------------------------------------------------------------------------
# Salidas para clientes (tipo delgado ISP): nada interno se filtra.
# --------------------------------------------------------------------------
class EnvioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    estado: str
    origen: dict
    destino: dict
    peso_kg: float
    volumen_m3: float
    is_international: bool
    sla_deadline: Optional[datetime] = None
    eta: Optional[datetime] = None
    vehicle_id: Optional[str] = None
    ruta_id: Optional[str] = None
    motivo: Optional[str] = None


class SeguimientoOut(BaseModel):
    """Lo mínimo que necesita el que pregunta "¿dónde va mi carga?"."""

    shipment_id: str
    estado: str
    eta: Optional[datetime] = None
    ultima_actualizacion: datetime
    motivo: Optional[str] = None


class HistorialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    desde: Optional[str] = None
    hasta: str
    motivo: Optional[str] = None
    creada_en: datetime


class IncidenteRequest(BaseModel):
    tipo: str = Field(min_length=2, max_length=40)
    confirmado: bool = True
    motivo: Optional[str] = None


class DevolucionRequest(BaseModel):
    motivo: Optional[str] = None


class PruebaEntregaRequest(BaseModel):
    nombre_recibe: str = Field(min_length=2, max_length=120)
    documento_recibe: Optional[str] = None
    firma_foto_url: Optional[str] = None
    comentario: Optional[str] = None
