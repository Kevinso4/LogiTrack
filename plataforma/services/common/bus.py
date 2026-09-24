"""Bus de eventos sobre RabbitMQ.

- Un exchange `topic` durable (`logitrack.events`); la routing key es el tipo de evento
  (p. ej. `shipment.created`), así cada consumidor se suscribe solo a lo que le interesa.
- Cada cola tiene su Dead Letter Queue (`<cola>.dlq`): tras agotar reintentos el mensaje
  se mueve ahí para inspección manual. Ningún mensaje se pierde en silencio.
- Formato del mensaje: {event_id, tipo, origen, ocurrido_en, datos}.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

import aio_pika

from .logs import request_id_var

EXCHANGE = "logitrack.events"
DLX = "logitrack.dlx"
REINTENTOS = 3

log = logging.getLogger("bus")

Handler = Callable[[dict], Awaitable[None]]


class EventBus:
    def __init__(self, url: str, servicio: str):
        self.url = url
        self.servicio = servicio
        self.conexion: aio_pika.abc.AbstractRobustConnection | None = None
        self.canal: aio_pika.abc.AbstractChannel | None = None
        self.exchange: aio_pika.abc.AbstractExchange | None = None
        self.dlx: aio_pika.abc.AbstractExchange | None = None

    @property
    def conectado(self) -> bool:
        return self.conexion is not None and not self.conexion.is_closed

    async def conectar(self, intentos: int = 60) -> None:
        for intento in range(1, intentos + 1):
            try:
                self.conexion = await aio_pika.connect_robust(self.url)
                break
            except Exception as exc:  # RabbitMQ aún arrancando
                log.warning("RabbitMQ no disponible (intento %s/%s): %s", intento, intentos, exc)
                await asyncio.sleep(2)
        else:
            raise RuntimeError("No se pudo conectar a RabbitMQ")
        self.canal = await self.conexion.channel()
        await self.canal.set_qos(prefetch_count=20)
        self.exchange = await self.canal.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        self.dlx = await self.canal.declare_exchange(DLX, aio_pika.ExchangeType.DIRECT, durable=True)
        log.info("Conectado a RabbitMQ")

    async def publicar(
        self, tipo: str, datos: dict, event_id: str | None = None, ocurrido_en: datetime | None = None
    ) -> str:
        cuerpo = {
            "event_id": event_id or str(uuid.uuid4()),
            "tipo": tipo,
            "origen": self.servicio,
            "ocurrido_en": (ocurrido_en or datetime.now(timezone.utc)).isoformat(),
            "datos": datos,
        }
        mensaje = aio_pika.Message(
            body=json.dumps(cuerpo, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=cuerpo["event_id"],
            type=tipo,
            headers={"x-request-id": request_id_var.get() or ""},
        )
        await self.exchange.publish(mensaje, routing_key=tipo)
        log.info("Evento publicado %s", tipo, extra={"evento": tipo, "routing_key": tipo})
        return cuerpo["event_id"]

    async def suscribir(self, cola: str, claves: list[str], handler: Handler) -> None:
        """Declara una cola durable con DLQ, la enlaza a las claves y empieza a consumir."""
        dlq = await self.canal.declare_queue(f"{cola}.dlq", durable=True)
        await dlq.bind(self.dlx, routing_key=f"{cola}.dlq")
        q = await self.canal.declare_queue(
            cola,
            durable=True,
            arguments={"x-dead-letter-exchange": DLX, "x-dead-letter-routing-key": f"{cola}.dlq"},
        )
        for clave in claves:
            await q.bind(self.exchange, routing_key=clave)

        async def al_recibir(mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
            try:
                evento = json.loads(mensaje.body)
            except ValueError:
                log.error("Mensaje ilegible en %s, se envía a la DLQ", cola)
                await mensaje.reject(requeue=False)
                return
            token = request_id_var.set((mensaje.headers or {}).get("x-request-id") or None)
            try:
                for intento in range(REINTENTOS):
                    try:
                        await handler(evento)
                        await mensaje.ack()
                        return
                    except Exception:
                        log.exception("Fallo procesando %s (intento %s)", evento.get("tipo"), intento + 1)
                        await asyncio.sleep(2**intento)
                log.error("Evento %s enviado a la DLQ %s.dlq", evento.get("event_id"), cola)
                await mensaje.reject(requeue=False)
            finally:
                request_id_var.reset(token)

        await q.consume(al_recibir)
        log.info("Suscrito %s a %s", cola, ", ".join(claves))

    async def suscribir_efimera(self, claves: list[str], handler: Handler) -> None:
        """Cola exclusiva y temporal (se borra al desconectar). La usa el gateway para el feed en vivo."""
        q = await self.canal.declare_queue("", exclusive=True, auto_delete=True)
        for clave in claves:
            await q.bind(self.exchange, routing_key=clave)

        async def al_recibir(mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
            async with mensaje.process(ignore_processed=True):
                try:
                    await handler(json.loads(mensaje.body))
                except Exception:
                    log.exception("Fallo en consumidor efímero")

        await q.consume(al_recibir)

    async def cerrar(self) -> None:
        if self.conexion:
            await self.conexion.close()
