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
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.interop import CAMPOS_VEHICULO_PROPIOS_A_COMPANERO, ESTADO_ACTIVO, traducir_estado_vehiculo
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
        params = self._construir_query(capacidad_min_kg, volumen_min_m3, refrigerado, hazmat)
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
                return self._parsear_respuesta(datos, volumen_min_m3)
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

    def _construir_query(
        self,
        capacidad_min_kg: float,
        volumen_min_m3: float,
        refrigerado: bool,
        hazmat: bool,
    ) -> Dict[str, Any]:
        """Dialecto de consulta: qué filtros entiende Fleet en la URL.

        Hook para el seam anticorrupción: el compañero no soporta
        `volumen_min_m3` y lo filtra en memoria (ver ClienteFleetCompanero).
        """
        params: Dict[str, Any] = {
            "capacidad_min_kg": capacidad_min_kg,
            "volumen_min_m3": volumen_min_m3,
        }
        if refrigerado:
            params["refrigerado"] = "true"
        if hazmat:
            params["hazmat"] = "true"
        return params

    def _parsear_respuesta(
        self, datos: List[Dict[str, Any]], volumen_min_m3: float
    ) -> List[VehiculoDisponible]:
        """Traduce la respuesta JSON de Fleet a `VehiculoDisponible`."""
        return [VehiculoDisponible.model_validate(d) for d in datos]


class ClienteFleetCompanero(ClienteFleetREST):
    """Seam 1 (PROMPT_INTEGRACION): Fleet del compañero con REST propio.

    Hereda del REST el timeout, los reintentos y el circuit breaker; cambia
    los HOOKS por los dialectos del compañero vía `app.interop`:

      * sin `volumen_min_m3` en la URL (no lo soporta): se filtra en memoria
        con `capacidad_m3`.
      * respuesta plana con `placa`, `tipo`, `zona_operacion`, `refrigerado`,
        `certificado_hazmat` y estados del vocabulario del compañero.
      * solo se consideran `activo` (disponible) los vehículos listos.
    """

    def _construir_query(
        self,
        capacidad_min_kg: float,
        volumen_min_m3: float,
        refrigerado: bool,
        hazmat: bool,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"capacidad_min_kg": capacidad_min_kg}
        if refrigerado:
            params["refrigerado"] = "true"
        if hazmat:
            params["hazmat"] = "true"
        return params

    def _parsear_respuesta(
        self, datos: List[Dict[str, Any]], volumen_min_m3: float
    ) -> List[VehiculoDisponible]:
        disponibles: List[VehiculoDisponible] = []
        for dato in datos:
            if (
                float(dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["capacity_m3"]) or 0)
                < volumen_min_m3
            ):
                continue
            estado = traducir_estado_vehiculo(dato.get("estado") or "", a_propio=True)
            if estado != ESTADO_ACTIVO:
                continue
            disponibles.append(
                VehiculoDisponible(
                    id=str(dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["id"])),
                    plate=str(dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["plate"])),
                    type=str(dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["type"])),
                    capacity_kg=float(
                        dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["capacity_kg"]) or 0
                    ),
                    capacity_m3=float(
                        dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["capacity_m3"]) or 0
                    ),
                    zona=str(dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["zona"])),
                    refrigeration_capable=bool(
                        dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["refrigeration_capable"])
                    ),
                    hazmat_certified=bool(
                        dato.get(CAMPOS_VEHICULO_PROPIOS_A_COMPANERO["hazmat_certified"])
                    ),
                )
            )
        return disponibles


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
