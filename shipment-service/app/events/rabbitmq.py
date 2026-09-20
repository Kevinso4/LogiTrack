"""Implementación del bus sobre RabbitMQ (exchange topic + DLQ)."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.events.base import EventoDominio, PublicadorEventos
from app.observabilidad import eventos_consumidos, eventos_publicados, log, trace_id_ctx

logger = logging.getLogger(__name__)

SUFIJO_DLX = ".dlx"


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
            self._canal = await self._conexion.channel(publisher_confirms=True)
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
        # publisher_confirms=True: el await no vuelve hasta que el broker confirma.
        await self._exchange.publish(mensaje, routing_key=evento.event_type)
        eventos_publicados.labels(evento.event_type).inc()
        log(
            logger,
            logging.INFO,
            "evento.publicado",
            event_type=evento.event_type,
            event_id=evento.event_id,
        )

    async def cerrar(self) -> None:
        if self._conexion and not self._conexion.is_closed:
            await self._conexion.close()


class ConsumidorRabbitMQ:
    """Cola duradera por dominio, con cola de mensajes fallidos (DLQ)."""

    def __init__(
        self,
        url: str,
        exchange: str,
        cola: str,
        routing_keys: list[str],
        manejador: Callable[[EventoDominio], Awaitable[None]],
        prefetch: int = 20,
    ) -> None:
        self._url = url
        self._nombre_exchange = exchange
        self._nombre_cola = cola
        self._routing_keys = routing_keys
        self._manejador = manejador
        self._prefetch = prefetch
        self._conexion: Optional[AbstractRobustConnection] = None

    async def iniciar(self) -> None:
        self._conexion = await aio_pika.connect_robust(self._url)
        canal = await self._conexion.channel()
        await canal.set_qos(prefetch_count=self._prefetch)

        exchange = await canal.declare_exchange(
            self._nombre_exchange, aio_pika.ExchangeType.TOPIC, durable=True
        )
        dlx = await canal.declare_exchange(
            self._nombre_exchange + SUFIJO_DLX,
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        cola_dlq = await canal.declare_queue(self._nombre_cola + ".dlq", durable=True)
        await cola_dlq.bind(dlx, routing_key="#")

        cola = await canal.declare_queue(
            self._nombre_cola,
            durable=True,
            arguments={"x-dead-letter-exchange": self._nombre_exchange + SUFIJO_DLX},
        )
        for rk in self._routing_keys:
            await cola.bind(exchange, routing_key=rk)

        await cola.consume(self._procesar)
        log(
            logger,
            logging.INFO,
            "consumidor.iniciado",
            cola=self._nombre_cola,
            routing_keys=self._routing_keys,
        )

    async def _procesar(self, mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
        evento: Optional[EventoDominio] = None
        try:
            evento = EventoDominio.desde_bytes(mensaje.body)
        except Exception:
            logger.exception("evento.ilegible")
            await mensaje.reject(requeue=False)  # directo a la DLQ
            return

        token = trace_id_ctx.set(evento.trace_id or "-")
        try:
            await self._manejador(evento)
            await mensaje.ack()
            eventos_consumidos.labels(evento.event_type, "ok").inc()
        except Exception:
            logger.exception("evento.fallido")
            eventos_consumidos.labels(evento.event_type, "error").inc()
            # Sin requeue: el mensaje va a la DLQ y no bloquea la cola.
            await mensaje.reject(requeue=False)
        finally:
            trace_id_ctx.reset(token)

    async def detener(self) -> None:
        if self._conexion and not self._conexion.is_closed:
            await self._conexion.close()
