"""Conector del bus: tarea de fondo que alista el puente.

Al arrancar el stack los servicios pueden llegar antes que RabbitMQ: el primer
intento de conexión falla con "Connection refused" y, si nadie vuelve a
intentar, el puente queda sordo para siempre. Esta tarea reintenta
`puente.iniciar()` con backoff exponencial (1 s, 2 s, 4 s … tope 30 s) y se
mantiene viva hasta el shutdown. Misma estrategia que `ConectorBus` de los
servicios.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import get_settings
from app.observabilidad import log

logger = logging.getLogger(__name__)


class ConectorPuente:
    """Reintenta arrancar el puente en segundo plano hasta que el bus responde."""

    def __init__(self, puente) -> None:
        self._puente = puente
        self._settings = get_settings()
        self._tarea: Optional[asyncio.Task] = None
        self._parar = asyncio.Event()

    def iniciar(self) -> None:
        self._parar.clear()
        self._tarea = asyncio.create_task(self._bucle(), name="conector-puente")

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self) -> None:
        espera = self._settings.bus_reintento_base_segundos
        listo = False
        while not self._parar.is_set():
            try:
                if not listo and not self._puente.activo:
                    await self._puente.iniciar()
                    log(logger, logging.INFO, "bus.listos")
                    listo = True
                # aio_pika se reanuda solo ante cortes: aquí solo se espera
                # la señal de apagado.
                await self._parar.wait()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                listo = False
                log(
                    logger,
                    logging.WARNING,
                    "bus.reintento",
                    error=str(exc),
                    reintento_en_segundos=espera,
                )
            if self._parar.is_set():
                return
            try:
                await asyncio.wait_for(self._parar.wait(), timeout=espera)
            except asyncio.TimeoutError:
                pass
            espera = min(espera * 2, self._settings.bus_reintento_maximo_segundos)
