"""Publicador RabbitMQ del servicio de ingesta.

Este servicio solo publica: no consume nada del bus (matriz de la sección 3).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.events.base import EventoDominio, PublicadorEventos
from app.observabilidad import eventos_fallidos, eventos_publicados, log

logger = logging.getLogger(__name__)


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
            self._canal = await self._conexion.channel(publisher_confirms=False)
            self._exchange = await self._canal.declare_exchange(
                self._nombre_exchange, aio_pika.ExchangeType.TOPIC, durable=True
            )
            log(logger, logging.INFO, "bus.conectado", exchange=self._nombre_exchange)

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
            await self._exchange.publish(mensaje, routing_key=evento.event_type)
        except Exception:
            eventos_fallidos.labels(evento.event_type).inc()
            raise
        eventos_publicados.labels(evento.event_type).inc()

    async def cerrar(self) -> None:
        if self._conexion and not self._conexion.is_closed:
            await self._conexion.close()
