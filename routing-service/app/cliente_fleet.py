"""Cliente síncrono hacia Fleet Service (sección 5g).

REST solo en el camino crítico: Routing decide qué vehículos cumplen la carga
con una llamada síncrona a /api/v1/vehiculos/disponibles. Lleva timeout,
reintentos con backoff y circuit breaker (sección 5f). Los fakes son la
implementación LSP del mismo contrato para tests y demo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import List, Optional

import httpx

from app.config import get_settings
from app.observabilidad import log
from app.schemas import VehiculoDisponible

logger = logging.getLogger(__name__)


class FleetNoDisponible(Exception):
    """Fleet está caído o el circuito está abierto. El motor lo trata igual:
    la ruta queda pendiente y NO se compensa en falso."""


class CircuitoAbierto(FleetNoDisponible):
    pass


class ClienteFleet(ABC):
    @abstractmethod
    async def buscar_disponibles(
        self,
        capacidad_min_kg: float,
        volumen_min_m3: float,
        refrigerado: bool = False,
        hazmat: bool = False,
    ) -> List[VehiculoDisponible]: ...


class ClienteFleetREST(ClienteFleet):
    def __init__(
        self,
        base_url: Optional[str] = None,
        transporte: Optional[httpx.AsyncBaseTransport] = None,
        timeout: Optional[float] = None,
        max_reintentos: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url or settings.fleet_url).rstrip("/")
        self._timeout = timeout or settings.fleet_timeout_segundos
        self._max_reintentos = max_reintentos or settings.fleet_max_reintentos
        self._limite_circuito = settings.circuito_errores_antes_de_abrir
        self._reset_circuito = settings.circuito_reset_segundos
        self._transporte = transporte
        self._fallos_consecutivos = 0
        self._abierto_hasta = 0.0

    async def buscar_disponibles(
        self,
        capacidad_min_kg: float,
        volumen_min_m3: float,
        refrigerado: bool = False,
        hazmat: bool = False,
    ) -> List[VehiculoDisponible]:
        if time.monotonic() < self._abierto_hasta:
            restante = self._abierto_hasta - time.monotonic()
            raise CircuitoAbierto(f"circuito abierto, reintento en {restante:.0f}s")
        params = {"capacidad_min_kg": capacidad_min_kg, "volumen_min_m3": volumen_min_m3}
        if refrigerado:
            params["refrigerado"] = "true"
        if hazmat:
            params["hazmat"] = "true"
        url = f"{self._base_url}/api/v1/vehiculos/disponibles"
        ultimo_error: Optional[BaseException] = None
        for intento in range(self._max_reintentos + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transporte
                ) as cliente:
                    respuesta = await cliente.get(url, params=params)
                    respuesta.raise_for_status()
                    datos = respuesta.json()
                self._fallos_consecutivos = 0
                return [VehiculoDisponible.model_validate(d) for d in datos]
            except (httpx.HTTPError, ValueError) as exc:
                ultimo_error = exc
                if self._max_reintentos - intento > 0:
                    await asyncio.sleep(0.2 * (intento + 1))  # backoff corto
        self._fallos_consecutivos += 1
        if self._fallos_consecutivos >= self._limite_circuito:
            self._abierto_hasta = time.monotonic() + self._reset_circuito
            log(
                logger,
                logging.WARNING,
                "fleet.circuito_abierto",
                errores=self._fallos_consecutivos,
                reset_s=self._reset_circuito,
            )
        raise FleetNoDisponible(f"fleet no disponible: {ultimo_error}") from ultimo_error


class ClienteFleetFake(ClienteFleet):
    """Implementación en memoria (LSP): tests y demo sin red ni Fleet."""

    def __init__(
        self,
        vehiculos: Optional[List[VehiculoDisponible]] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self._vehiculos = vehiculos or []
        self._error = error
        self.llamadas = 0

    async def buscar_disponibles(
        self,
        capacidad_min_kg: float,
        volumen_min_m3: float,
        refrigerado: bool = False,
        hazmat: bool = False,
    ) -> List[VehiculoDisponible]:
        self.llamadas += 1
        if self._error is not None:
            raise self._error
        return list(self._vehiculos)
