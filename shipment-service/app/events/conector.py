"""Conector del bus: tarea de fondo que alista publicador y consumidor.

Al arrancar el stack los servicios pueden llegar antes que RabbitMQ: el primer
intento de conexión falla con "Connection refused" y, si nadie vuelve a
intentar, el servicio queda sordo al bus para siempre. Esta tarea reintenta
`publicador.conectar()` y `consumidor.iniciar()` con backoff exponencial
(1 s, 2 s, 4 s … tope 30 s) y se mantiene viva hasta el shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.config import get_settings
from app.events.base import PublicadorEventos
from app.observabilidad import log

logger = logging.getLogger(__name__)


class ConectorBus:
    """Reintenta conectar el publicador y arrancar el consumidor en segundo plano.

    `consumidor` es opcional: los servicios que solo publican (Tracking, según
    la matriz de la sección 3) no lo pasan y aquí solo se reintenta el
    publicador. El `activo` del consumidor evita arrancarlo dos veces.
    """

    def __init__(self, publicador: PublicadorEventos, consumidor=None) -> None:
        self._publicador = publicador
        self._consumidor = consumidor
        self._settings = get_settings()
        self._tarea: Optional[asyncio.Task] = None
        self._parar = asyncio.Event()

    def iniciar(self) -> None:
        self._parar.clear()
        self._tarea = asyncio.create_task(self._bucle(), name="conector-bus")

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
                if not listo:
                    await self._publicador.conectar()
                    if self._consumidor is not None and not self._consumidor.activo:
                        await self._consumidor.iniciar()
                    log(logger, logging.INFO, "bus.listos")
                    listo = True
                # Conexiones robustas: aio_pika se reanuda solo ante cortes.
                # Aquí la tarea solo espera la señal de apagado.
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
