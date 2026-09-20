"""Contratos de la API de ingesta y de consulta."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LecturaCruda(BaseModel):
    """Lectura tal como la manda el dispositivo.

    Se aceptan campos desconocidos a propósito: cada fabricante nombra las
    cosas a su manera y el renombrado ocurre en `normalizacion.py`.
    """

    model_config = ConfigDict(extra="allow")

    vehicle_id: Optional[str] = Field(default=None, examples=["c0ffee-1234"])
    timestamp: Optional[Any] = Field(default=None, examples=["2026-09-20T13:00:00Z"])
    lat: Optional[float] = None
    lon: Optional[float] = None
    velocidad: Optional[float] = None
    temperatura_motor: Optional[float] = None
    combustible: Optional[float] = None
    odometro: Optional[float] = None
    horas_motor: Optional[float] = None
    codigos_obd2: Optional[Any] = None
    device_id: Optional[str] = None


class LoteTelemetria(BaseModel):
    """Lote de lecturas. Los dispositivos acumulan y envían cada N segundos."""

    device_id: Optional[str] = None
    fabricante: str = Field(default="generico", examples=["queclink"])
    unidades: Optional[Dict[str, str]] = Field(
        default=None,
        description=(
            "Override de unidades del perfil. "
            "Claves: velocidad, temperatura, distancia, combustible."
        ),
        examples=[{"velocidad": "mph", "temperatura": "F", "distancia": "mi"}],
    )
    lecturas: List[LecturaCruda] = Field(min_length=1)


class LecturaRechazada(BaseModel):
    indice: int
    motivo: str
    detalle: str = ""


class RespuestaIngesta(BaseModel):
    recibidas: int
    aceptadas: int
    rechazadas: int
    duplicadas: int = 0
    errores: List[LecturaRechazada] = Field(default_factory=list)
    duracion_ms: float


class LecturaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: str
    time: datetime
    lat: float
    lon: float
    speed_kmh: Optional[float] = None
    engine_temp_c: Optional[float] = None
    fuel_level_pct: Optional[float] = None
    odometer_km: Optional[float] = None
    engine_hours: Optional[float] = None
    obd2_codes: List[str] = Field(default_factory=list)
    fabricante: Optional[str] = None


class RecorridoOut(BaseModel):
    vehicle_id: str
    desde: datetime
    hasta: datetime
    lecturas: int
    distancia_km: float
    velocidad_promedio_kmh: Optional[float] = None
    velocidad_maxima_kmh: Optional[float] = None
    puntos: List[LecturaOut]


class AgregadoOut(BaseModel):
    """Contenido del evento `telemetry.aggregated`."""

    vehicle_id: str
    ventana_inicio: datetime
    ventana_fin: datetime
    lecturas: int
    velocidad_promedio_kmh: Optional[float] = None
    velocidad_maxima_kmh: Optional[float] = None
    temperatura_motor_max_c: Optional[float] = None
    combustible_pct: Optional[float] = None
    odometro_km: Optional[float] = None
    distancia_km: float = 0.0
    horas_motor: Optional[float] = None
    codigos_obd2: List[str] = Field(default_factory=list)
    ultima_posicion: Optional[Dict[str, float]] = None
    detenido: bool = False


class Salud(BaseModel):
    estado: str
    servicio: str
    version: str
    dependencias: dict = Field(default_factory=dict)
