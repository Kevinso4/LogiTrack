"""Contratos de entrada/salida del Routing Service (ISP, sección 5e).

`ShipmentCreatedPayload`, `TelemetryAggregatedPayload` y
`VehicleStatusChangedPayload` son contratos de eventos consumidos: claves en
inglés, igual que en la matriz del bus (sección 3 del documento).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PuntoGps(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    direccion: str = Field(min_length=3, max_length=200)


class VentanaEntrega(BaseModel):
    desde: datetime
    hasta: datetime


class ShipmentCreatedPayload(BaseModel):
    """Contrato de entrada de Routing. El publica Shipment Service y, si el
    envío es internacional, también lo consume Customs. Documentado en el
    README raíz del proyecto."""

    shipment_id: str
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


class TelemetryAggregatedPayload(BaseModel):
    """Forma exacta del payload de telemetry.aggregated (Tracking Service)."""

    vehicle_id: str
    ventana_inicio: datetime
    ventana_fin: datetime
    lecturas: int = 0
    velocidad_promedio_kmh: Optional[float] = None
    velocidad_maxima_kmh: Optional[float] = None
    temperatura_motor_max_c: Optional[float] = None
    combustible_pct: Optional[float] = None
    odometro_km: Optional[float] = None
    distancia_km: float = 0.0
    horas_motor: Optional[float] = None
    codigos_obd2: List[str] = Field(default_factory=list)
    ultima_posicion: dict = Field(default_factory=dict)
    detenido: bool = False


class VehicleStatusChangedPayload(BaseModel):
    """Forma exacta del payload de vehicle.status_changed (Fleet Service)."""

    vehicle_id: str
    plate: Optional[str] = None
    estado_anterior: Optional[str] = None
    estado_nuevo: str
    asignable: Optional[bool] = None
    motivo: Optional[str] = None
    zona: Optional[str] = None
    origen: Optional[str] = None


class VehiculoDisponible(BaseModel):
    """Contrato delgado de /api/v1/vehiculos/disponibles que consume Fleet."""

    id: str
    plate: str
    type: str
    capacity_kg: float
    capacity_m3: float
    zona: str
    refrigeration_capable: bool
    hazmat_certified: bool


class ParadaOut(BaseModel):
    orden: int
    direccion: str
    lat: float
    lng: float
    ventana_desde: Optional[datetime] = None
    ventana_hasta: Optional[datetime] = None
    eta_llegada: Optional[datetime] = None


class RutaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    shipment_id: str
    vehicle_id: Optional[str] = None
    vehicle_plate: Optional[str] = None
    estado: str
    origen: dict
    destino: dict
    distancia_km: Optional[float] = None
    duracion_min: Optional[float] = None
    eta_actual: Optional[datetime] = None
    tipo_calculo: Optional[str] = None
    motivo: Optional[str] = None


class NavegacionOut(BaseModel):
    """Contrato delgado de la app del conductor (ISP, sección 5e): paradas
    ordenadas con su ventana, geometría de la ruta y el ETA. Sin datos de
    envíos ajenos ni de clientes."""

    ruta_id: str
    shipment_id: str
    vehicle_id: Optional[str] = None
    plate: Optional[str] = None
    eta: Optional[datetime] = None
    distancia_km: Optional[float] = None
    tipo_calculo: Optional[str] = None
    geometria: List[dict] = Field(default_factory=list)
    paradas: List[ParadaOut] = Field(default_factory=list)


class RecalcularRequest(BaseModel):
    causa: str = Field(default="manual", max_length=50)
