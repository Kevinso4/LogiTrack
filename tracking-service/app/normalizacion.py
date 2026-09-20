"""Validación y normalización de la telemetría cruda.

Cada fabricante de hardware GPS manda lo suyo: unos en mph y grados
Fahrenheit, otros con los campos abreviados. Aquí se traduce todo a una única
forma canónica (km/h, °C, km, %) ANTES de tocar la base. El servicio no
analiza nada más: eso es trabajo de Routing y de Maintenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------
# Factores de conversión
# --------------------------------------------------------------------------
VELOCIDAD_A_KMH = {"kmh": 1.0, "km/h": 1.0, "mph": 1.609344, "ms": 3.6, "m/s": 3.6, "kn": 1.852}
DISTANCIA_A_KM = {"km": 1.0, "mi": 1.609344, "m": 0.001, "millas": 1.609344}


def a_celsius(valor: float, unidad: str) -> float:
    unidad = unidad.upper()
    if unidad in ("C", "°C"):
        return valor
    if unidad in ("F", "°F"):
        return (valor - 32.0) * 5.0 / 9.0
    if unidad == "K":
        return valor - 273.15
    raise ErrorNormalizacion("unidad_desconocida", f"temperatura '{unidad}'")


def a_porcentaje(valor: float, unidad: str) -> float:
    unidad = unidad.lower()
    if unidad in ("pct", "%", "porcentaje"):
        return valor
    if unidad in ("fraccion", "ratio"):
        return valor * 100.0
    raise ErrorNormalizacion("unidad_desconocida", f"combustible '{unidad}'")


class ErrorNormalizacion(Exception):
    """Rechazo de una lectura concreta; el resto del lote continúa."""

    def __init__(self, motivo: str, detalle: str = ""):
        self.motivo = motivo
        self.detalle = detalle
        super().__init__(f"{motivo}: {detalle}" if detalle else motivo)


# --------------------------------------------------------------------------
# Perfiles de fabricante
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PerfilFabricante:
    nombre: str
    unidad_velocidad: str = "kmh"
    unidad_temperatura: str = "C"
    unidad_distancia: str = "km"
    unidad_combustible: str = "pct"
    # Nombre propio del fabricante -> nombre canónico.
    alias: Dict[str, str] = field(default_factory=dict)


PERFILES: Dict[str, PerfilFabricante] = {
    "generico": PerfilFabricante(nombre="generico"),
    "teltonika": PerfilFabricante(
        nombre="teltonika",
        unidad_velocidad="kmh",
        unidad_temperatura="C",
        unidad_distancia="m",
        alias={
            "ts": "timestamp",
            "lat": "lat",
            "lng": "lon",
            "spd": "velocidad",
            "tmp": "temperatura_motor",
            "odo": "odometro",
            "fuel": "combustible",
            "eng_h": "horas_motor",
            "dtc": "codigos_obd2",
        },
    ),
    "queclink": PerfilFabricante(
        nombre="queclink",
        unidad_velocidad="mph",
        unidad_temperatura="F",
        unidad_distancia="mi",
        alias={
            "time": "timestamp",
            "latitude": "lat",
            "longitude": "lon",
            "speed": "velocidad",
            "engine_temp": "temperatura_motor",
            "odometer": "odometro",
            "fuel_level": "combustible",
            "engine_hours": "horas_motor",
            "obd_codes": "codigos_obd2",
        },
    ),
    "concox": PerfilFabricante(
        nombre="concox",
        unidad_velocidad="kn",
        unidad_temperatura="C",
        unidad_distancia="km",
        unidad_combustible="fraccion",
    ),
}


def obtener_perfil(fabricante: Optional[str]) -> PerfilFabricante:
    return PERFILES.get((fabricante or "generico").lower(), PERFILES["generico"])


# --------------------------------------------------------------------------
# Lectura canónica
# --------------------------------------------------------------------------
@dataclass
class LecturaNormalizada:
    vehicle_id: str
    timestamp: datetime
    lat: float
    lon: float
    velocidad_kmh: Optional[float]
    temperatura_motor_c: Optional[float]
    combustible_pct: Optional[float]
    odometro_km: Optional[float]
    horas_motor: Optional[float]
    codigos_obd2: List[str]
    device_id: Optional[str]
    fabricante: str

    def como_fila(self) -> Dict[str, Any]:
        return {
            "time": self.timestamp,
            "vehicle_id": self.vehicle_id,
            "device_id": self.device_id,
            "fabricante": self.fabricante,
            "lat": self.lat,
            "lon": self.lon,
            "speed_kmh": self.velocidad_kmh,
            "engine_temp_c": self.temperatura_motor_c,
            "fuel_level_pct": self.combustible_pct,
            "odometer_km": self.odometro_km,
            "engine_hours": self.horas_motor,
            "obd2_codes": self.codigos_obd2,
        }


def _numero(valor: Any, campo: str) -> Optional[float]:
    if valor is None or valor == "":
        return None
    try:
        return float(valor)
    except (TypeError, ValueError) as exc:
        raise ErrorNormalizacion("valor_no_numerico", campo) from exc


def _fecha(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        fecha = valor
    elif isinstance(valor, (int, float)):  # epoch en segundos
        fecha = datetime.fromtimestamp(float(valor), tz=timezone.utc)
    elif isinstance(valor, str):
        try:
            fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ErrorNormalizacion("timestamp_invalido", valor[:40]) from exc
    else:
        raise ErrorNormalizacion("timestamp_invalido", str(valor)[:40])
    if fecha.tzinfo is None:
        fecha = fecha.replace(tzinfo=timezone.utc)
    return fecha.astimezone(timezone.utc)


def normalizar(
    cruda: Dict[str, Any],
    perfil: PerfilFabricante,
    unidades: Optional[Dict[str, str]] = None,
    device_id: Optional[str] = None,
    velocidad_maxima_kmh: float = 200.0,
    tolerancia_futuro_minutos: int = 5,
    antiguedad_maxima_horas: int = 72,
    ahora: Optional[datetime] = None,
) -> LecturaNormalizada:
    """Traduce una lectura cruda a la forma canónica o la rechaza."""
    unidades = unidades or {}
    ahora = ahora or datetime.now(timezone.utc)

    # 1) Renombrado según el fabricante.
    datos: Dict[str, Any] = {}
    for clave, valor in cruda.items():
        datos[perfil.alias.get(clave, clave)] = valor

    # 2) Campos obligatorios.
    vehicle_id = datos.get("vehicle_id") or datos.get("vehiculo_id")
    if not vehicle_id:
        raise ErrorNormalizacion("campo_faltante", "vehicle_id")
    if datos.get("timestamp") is None:
        raise ErrorNormalizacion("campo_faltante", "timestamp")

    timestamp = _fecha(datos["timestamp"])
    if timestamp > ahora + timedelta(minutes=tolerancia_futuro_minutos):
        raise ErrorNormalizacion("timestamp_futuro", timestamp.isoformat())
    if timestamp < ahora - timedelta(hours=antiguedad_maxima_horas):
        raise ErrorNormalizacion("timestamp_antiguo", timestamp.isoformat())

    lat = _numero(datos.get("lat"), "lat")
    lon = _numero(datos.get("lon"), "lon")
    if lat is None or lon is None:
        raise ErrorNormalizacion("campo_faltante", "lat/lon")
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise ErrorNormalizacion("coordenada_invalida", f"{lat},{lon}")

    # 3) Conversión de unidades.
    u_vel = (unidades.get("velocidad") or perfil.unidad_velocidad).lower()
    factor_vel = VELOCIDAD_A_KMH.get(u_vel)
    if factor_vel is None:
        raise ErrorNormalizacion("unidad_desconocida", f"velocidad '{u_vel}'")

    u_dist = (unidades.get("distancia") or perfil.unidad_distancia).lower()
    factor_dist = DISTANCIA_A_KM.get(u_dist)
    if factor_dist is None:
        raise ErrorNormalizacion("unidad_desconocida", f"distancia '{u_dist}'")

    velocidad = _numero(datos.get("velocidad"), "velocidad")
    velocidad_kmh = round(velocidad * factor_vel, 3) if velocidad is not None else None
    if velocidad_kmh is not None and not (0.0 <= velocidad_kmh <= velocidad_maxima_kmh):
        raise ErrorNormalizacion("velocidad_fuera_de_rango", f"{velocidad_kmh} km/h")

    temperatura = _numero(datos.get("temperatura_motor"), "temperatura_motor")
    temperatura_c = (
        round(a_celsius(temperatura, unidades.get("temperatura") or perfil.unidad_temperatura), 2)
        if temperatura is not None
        else None
    )

    combustible = _numero(datos.get("combustible"), "combustible")
    combustible_pct = (
        round(
            a_porcentaje(combustible, unidades.get("combustible") or perfil.unidad_combustible), 2
        )
        if combustible is not None
        else None
    )
    if combustible_pct is not None and not (0.0 <= combustible_pct <= 100.0):
        raise ErrorNormalizacion("combustible_fuera_de_rango", str(combustible_pct))

    odometro = _numero(datos.get("odometro"), "odometro")
    odometro_km = round(odometro * factor_dist, 3) if odometro is not None else None
    if odometro_km is not None and odometro_km < 0:
        raise ErrorNormalizacion("odometro_invalido", str(odometro_km))

    horas_motor = _numero(datos.get("horas_motor"), "horas_motor")

    codigos = datos.get("codigos_obd2") or []
    if isinstance(codigos, str):
        codigos = [c.strip() for c in codigos.split(",") if c.strip()]
    if not isinstance(codigos, list):
        raise ErrorNormalizacion("codigos_obd2_invalidos", str(codigos)[:40])

    return LecturaNormalizada(
        vehicle_id=str(vehicle_id),
        timestamp=timestamp,
        lat=lat,
        lon=lon,
        velocidad_kmh=velocidad_kmh,
        temperatura_motor_c=temperatura_c,
        combustible_pct=combustible_pct,
        odometro_km=odometro_km,
        horas_motor=horas_motor,
        codigos_obd2=[str(c).upper() for c in codigos],
        device_id=str(datos.get("device_id") or device_id or "") or None,
        fabricante=perfil.nombre,
    )


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine. Se usa para el recorrido y para la distancia de la ventana."""
    radio = 6371.0088
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return round(2 * radio * asin(sqrt(a)), 4)
