"""Publicador RabbitMQ del servicio de ingesta.

Este servicio solo publica: no consume nada del bus (matriz de la sección 3).

`telemetry.raw` NO tiene consumidores por diseño (es persistencia histórica,
documentado también en `app/models.py`): se publica best-effort, sin outbox y
SIN `mandatory`. Aplicarle `mandatory` devolvería todos los mensajes y
llenaría de falsos positivos el servicio de mayor caudal del sistema.
`telemetry.aggregated`, que sí consumen Routing y Maintenance, va con
`mandatory`: si ninguna cola está suscrita, el broker lo devuelve y el
`return_callbacks` del canal (única señal: no hay publisher confirms aquí,
priorizamos throughput) lo cuenta y lo loguea.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.events.base import EventoDominio, PublicadorEventos
from app.observabilidad import (
    eventos_fallidos,
    eventos_no_entregados,
    eventos_publicados,
    log,
)

logger = logging.getLogger(__name__)

# Matriz de eventos (sección 3 del documento): solo esto tiene consumidores.
EVENTOS_CON_CONSUMIDORES = {
    "telemetry.aggregated",  # routing-service (routing.inbox), maintenance
}


class PublicadorRabbitMQ(PublicadorEventos):
    def __init__(self, url: str, exchange: str) -> None:
        self._url = url
        self._nombre_exchange = exchange
        self._conexion: Optional[AbstractRobustConnection] = None
        self._canal: Optional[aio_pika.abc.AbstractChannel] = None
        self._exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self._lock = asyncio.Lock()

    async def conectar(self) -> None:
        async with self._lock:
            if self._conexion and not self._conexion.is_closed:
                return
            self._conexion = await aio_pika.connect_robust(self._url)
            # Sin publisher_confirms en la ruta de ingesta: prioriza throughput.
            # Por eso los mensajes devueltos (mandatory sin cola destino) no
            # lanzan DeliveryError: `return_callbacks` es la única señal.
            self._canal = await self._conexion.channel(publisher_confirms=False)
            self._canal.return_callbacks.add(self._al_volver)
            self._exchange = await self._canal.declare_exchange(
                self._nombre_exchange, aio_pika.ExchangeType.TOPIC, durable=True
            )
            log(logger, logging.INFO, "bus.conectado", exchange=self._nombre_exchange)

    def _al_volver(self, mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
        """Mensaje devuelto por el broker (mandatory sin cola destino).

        Solo puede ocurrir para `telemetry.aggregated`: `telemetry.raw` se
        publica sin `mandatory` (no tiene consumidores por diseño).
        """
        event_type = getattr(mensaje, "routing_key", None) or "desconocido"
        eventos_no_entregados.labels(event_type, "no_enrutado").inc()
        log(
            logger,
            logging.WARNING,
            "evento.no_enrutado",
            event_type=event_type,
        )

    async def publicar(self, evento: EventoDominio) -> None:
        if self._exchange is None:
            await self.conectar()
        assert self._exchange is not None
        mensaje = aio_pika.Message(
            body=evento.a_bytes(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=evento.event_id,
            headers={"trace_id": evento.trace_id or "-", "producer": evento.producer},
        )
        try:
            await self._exchange.publish(
                mensaje,
                routing_key=evento.event_type,
                mandatory=evento.event_type in EVENTOS_CON_CONSUMIDORES,
            )
        except Exception:
            eventos_fallidos.labels(evento.event_type).inc()
            raise
        eventos_publicados.labels(evento.event_type).inc()

    async def cerrar(self) -> None:
        if self._conexion and not self._conexion.is_closed:
            await self._conexion.close()
