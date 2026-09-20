"""Proveedor de mapas (OCP + LSP + DIP, secciones 5e y 5f).

El motor de rutas depende de `ProveedorMapas`, nunca del SDK de Mapbox.
Anyadir HERE es implementar esta interfaz y cambiar `PROVEEDOR_MAPAS`, sin
tocar el motor. Este módulo concentra TODA la dependencia del proveedor de
mapas del sistema.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from math import atan2, cos, radians, sin, sqrt
from typing import List, Sequence

import httpx
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)


class PuntoParada(BaseModel):
    lat: float
    lng: float


class ResultadoRuta(BaseModel):
    distancia_km: float
    duracion_min: float
    geometria: List[dict] = Field(default_factory=list)
    tipo_calculo: str = "calculado"


class ErrorProveedorExterno(Exception):
    """Cualquier fallo del proveedor de mapas. El motor lo trata igual:
    conserva la última ruta y marca el ETA como estimado (sección 5f)."""


class ProveedorMapas(ABC):
    @abstractmethod
    async def optimizar_ruta(self, paradas: Sequence[PuntoParada]) -> ResultadoRuta: ...


def distancia_haversine_km(a: PuntoParada, b: PuntoParada) -> float:
    R = 6371.0
    dlat = radians(b.lat - a.lat)
    dlon = radians(b.lng - a.lng)
    x = sin(dlat / 2) ** 2 + cos(radians(a.lat)) * cos(radians(b.lat)) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(x), sqrt(1 - x))


class SimuladoProveedorMapas(ProveedorMapas):
    """Determinista, para dev/demo y tests (sin token ni red).

    Estimación por tramos rectos (haversine), factor de rotero para la
    curvatura de la vía y velocidad de crucero configurable. La duración de
    conducción la ajusta luego el dominio (descansos obligatorios).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._velocidad = settings.velocidad_estimacion_kmh
        self._factor = settings.factor_rotero

    async def optimizar_ruta(self, paradas: Sequence[PuntoParada]) -> ResultadoRuta:
        if len(paradas) < 2:
            raise ErrorProveedorExterno("Se necesitan al menos origen y destino")
        total_km = 0.0
        geometria: List[dict] = []
        for i in range(len(paradas) - 1):
            a, b = paradas[i], paradas[i + 1]
            total_km += distancia_haversine_km(a, b)
            geometria.append({"lat": a.lat, "lng": a.lng})
        geometria.append({"lat": paradas[-1].lat, "lng": paradas[-1].lng})
        total_km *= self._factor
        duracion = total_km / self._velocidad * 60
        return ResultadoRuta(
            distancia_km=round(total_km, 2),
            duracion_min=round(duracion, 1),
            geometria=geometria,
        )


class MapboxProveedorMapas(ProveedorMapas):
    """Implementación sobre la Directions API de Mapbox (HTTP).

    Un fallo de red o un 4xx/5xx se convierte en `ErrorProveedorExterno`; el
    motor conserva la última ruta y marca el ETA como estimado.
    """

    def __init__(
        self,
        token: str | None = None,
        url_base: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        settings = get_settings()
        self._token = token or settings.mapbox_token
        self._url_base = (url_base or settings.mapbox_url_base).rstrip("/")
        self._timeout = timeout

    async def optimizar_ruta(self, paradas: Sequence[PuntoParada]) -> ResultadoRuta:
        if not self._token:
            raise ErrorProveedorExterno("mapbox_sin_token")
        coords = ";".join(f"{p.lng},{p.lat}" for p in paradas)
        url = f"{self._url_base}/directions/v5/mapbox/driving/{coords}"
        params = {"access_token": self._token, "geometries": "geojson", "overview": "full"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as cliente:
                respuesta = await cliente.get(url, params=params)
                respuesta.raise_for_status()
                datos = respuesta.json()
        except httpx.HTTPError as exc:
            raise ErrorProveedorExterno(f"mapbox_http_error: {exc}") from exc
        ruta = datos["routes"][0]
        return ResultadoRuta(
            distancia_km=round(ruta["distance"] / 1000, 2),
            duracion_min=round(ruta["duration"] / 60, 1),
            geometria=[{"lat": c[1], "lng": c[0]} for c in ruta["geometry"]["coordinates"]],
        )


class ProveedorMapasQueFalla(ProveedorMapas):
    """Seam de pruebas: simula el proveedor de mapas caído."""

    async def optimizar_ruta(self, paradas: Sequence[PuntoParada]) -> ResultadoRuta:
        raise ErrorProveedorExterno("proveedor_simulado_caido")


def fabricar_proveedor() -> ProveedorMapas:
    settings = get_settings()
    if settings.proveedor_mapas == "mapbox":
        return MapboxProveedorMapas()
    return SimuladoProveedorMapas()
