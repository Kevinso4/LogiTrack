"""Cliente REST interno con timeout, reintentos con backoff+jitter y circuit breaker."""
import logging
import random
import time

import httpx

from .logs import request_id_var

log = logging.getLogger("cliente_http")


class CircuitoAbierto(Exception):
    pass


class CircuitBreaker:
    """Cerrado → (5 fallos en 30 s) → Abierto → (tras 30 s) → Semiabierto → una prueba."""

    def __init__(self, nombre: str, fallos_max: int = 5, ventana_s: float = 30, espera_s: float = 30):
        self.nombre = nombre
        self.fallos_max = fallos_max
        self.ventana_s = ventana_s
        self.espera_s = espera_s
        self.fallos: list[float] = []
        self.abierto_desde: float | None = None

    @property
    def estado(self) -> str:
        if self.abierto_desde is None:
            return "cerrado"
        if time.monotonic() - self.abierto_desde >= self.espera_s:
            return "semiabierto"
        return "abierto"

    def antes(self) -> None:
        if self.estado == "abierto":
            raise CircuitoAbierto(self.nombre)

    def exito(self) -> None:
        self.fallos.clear()
        self.abierto_desde = None

    def fallo(self) -> None:
        ahora = time.monotonic()
        if self.estado == "semiabierto":
            self.abierto_desde = ahora
            return
        self.fallos = [t for t in self.fallos if ahora - t < self.ventana_s] + [ahora]
        if len(self.fallos) >= self.fallos_max:
            log.warning("Circuito %s ABIERTO", self.nombre)
            self.abierto_desde = ahora


class ClienteServicio:
    def __init__(self, nombre: str, base_url: str, timeout_s: float = 2.0, reintentos: int = 3):
        self.nombre = nombre
        self.cliente = httpx.Client(base_url=base_url, timeout=timeout_s)
        self.reintentos = reintentos
        self.circuito = CircuitBreaker(nombre)

    def get(self, ruta: str, **params) -> httpx.Response:
        """Solo GET: es idempotente y por eso puede reintentarse sin riesgo."""
        params = {k: v for k, v in params.items() if v is not None}
        cabeceras = {"X-User-Role": "servicio", "X-Request-ID": request_id_var.get() or ""}
        ultimo_error: Exception | None = None
        for intento in range(self.reintentos):
            self.circuito.antes()
            try:
                resp = self.cliente.get(ruta, params=params, headers=cabeceras)
                if resp.status_code >= 500:
                    raise httpx.HTTPStatusError("5xx", request=resp.request, response=resp)
                self.circuito.exito()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                ultimo_error = exc
                self.circuito.fallo()
                espera = (2**intento) + random.uniform(0, 0.5)
                log.warning("GET %s%s falló (%s); reintento en %.1fs", self.nombre, ruta, exc, espera)
                time.sleep(espera)
        raise ultimo_error  # type: ignore[misc]
