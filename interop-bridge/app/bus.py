"""Puente sobre RabbitMQ: declara exchanges y colas y traduce en vivo.

Dos mundos conectados sin que ninguno sepa del otro (seam 2):

  * entrante: consumimos `logitrack.fleet` (rk `vehicle.status_changed`) y
    republicamos en `logitrack.events`.
  * saliente: consumimos `logitrack.events` (rk `shipment.incident`) y
    republicamos en `logitrack.shipment`.
  * telemetría: consumimos `logitrack.events` (rk `telemetry.aggregated`)
    y republicamos en `logitrack.tracking`, que es donde su Maintenance
    escucha. Sin esta tercera dirección su motor de reglas no recibe una
    sola lectura y nunca abre una alerta.

Exchanges y colas duras, con DLQ por cola (`<exchange>.dlx` / `<cola>.dlq`):
un mensaje no traducible o no publicable nunca bloquea la cola.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import aio_pika
from aio_pika.abc import AbstractRobustConnection

from app.base import EventoDominio
from app.config import Settings, get_settings
from app.observabilidad import log, trace_id_ctx
from app.traductor import (
    EVENTO_ENTRANTE,
    EVENTO_SALIENTE,
    EVENTO_TELEMETRIA,
    traducir_entrante,
    traducir_saliente,
    traducir_telemetria_saliente,
)

logger = logging.getLogger(__name__)

SUFIJO_DLX = ".dlx"


class PuenteRabbitMQ:
    """Una conexión robusta de aio_pika; el conector la reanuda si se cae."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._conexion: Optional[AbstractRobustConnection] = None
        self._exchange_eventos: Optional[aio_pika.abc.AbstractExchange] = None
        self._exchange_shipment: Optional[aio_pika.abc.AbstractExchange] = None
        self._exchange_tracking: Optional[aio_pika.abc.AbstractExchange] = None
        self._activo = False

    @property
    def activo(self) -> bool:
        """Ya está alistado en el bus: evita que el conector lo arranque dos veces."""
        return self._activo

    async def iniciar(self) -> None:
        if self._activo:
            return
        s = self._settings
        try:
            self._conexion = await aio_pika.connect_robust(s.rabbitmq_url)

            canal = await self._conexion.channel()
            await canal.set_qos(prefetch_count=20)
            fleet = await self._declarar_exchange(canal, s.exchange_fleet)
            eventos = await self._declarar_exchange(canal, s.exchange_eventos)
            await self._declarar_exchange(canal, s.exchange_shipment)
            await self._declarar_exchange(canal, s.exchange_tracking)

            cola_entrante = await self._declarar_cola(canal, s.cola_fleet, s.exchange_fleet)
            await cola_entrante.bind(fleet, routing_key=EVENTO_ENTRANTE)
            await cola_entrante.consume(self._procesar_entrante)

            cola_saliente = await self._declarar_cola(canal, s.cola_shipment, s.exchange_eventos)
            await cola_saliente.bind(eventos, routing_key=EVENTO_SALIENTE)
            await cola_saliente.consume(self._procesar_saliente)

            # Cola propia para la telemetría: separarla de shipment.incident
            # evita que un pico de agregados (uno por vehículo por minuto)
            # retrase una incidencia, que es lo urgente de las dos.
            cola_telemetria = await self._declarar_cola(
                canal, s.cola_telemetria, s.exchange_eventos
            )
            await cola_telemetria.bind(eventos, routing_key=EVENTO_TELEMETRIA)
            await cola_telemetria.consume(self._procesar_telemetria)

            # Canal de publicación aparte (el de consumo queda tomado por aio_pika).
            publicacion = await self._conexion.channel(
                publisher_confirms=True, on_return_raises=True
            )
            self._exchange_eventos = await publicacion.declare_exchange(
                s.exchange_eventos, aio_pika.ExchangeType.TOPIC, durable=True
            )
            self._exchange_shipment = await publicacion.declare_exchange(
                s.exchange_shipment, aio_pika.ExchangeType.TOPIC, durable=True
            )
            self._exchange_tracking = await publicacion.declare_exchange(
                s.exchange_tracking, aio_pika.ExchangeType.TOPIC, durable=True
            )

            self._activo = True
            log(
                logger,
                logging.INFO,
                "puente.iniciado",
                cola_fleet=s.cola_fleet,
                cola_shipment=s.cola_shipment,
                cola_telemetria=s.cola_telemetria,
            )
        except Exception:
            # Si la declaración falla a medias, no dejar la conexión huérfana.
            if self._conexion and not self._conexion.is_closed:
                await self._conexion.close()
            self._conexion = None
            raise

    async def _declarar_exchange(self, canal, nombre: str) -> aio_pika.abc.AbstractExchange:
        await canal.declare_exchange(nombre + SUFIJO_DLX, aio_pika.ExchangeType.TOPIC, durable=True)
        return await canal.declare_exchange(nombre, aio_pika.ExchangeType.TOPIC, durable=True)

    async def _declarar_cola(self, canal, nombre: str, origen: str):
        dlq = await canal.declare_queue(nombre + ".dlq", durable=True)
        dlx = await canal.declare_exchange(
            origen + SUFIJO_DLX, aio_pika.ExchangeType.TOPIC, durable=True
        )
        await dlq.bind(dlx, routing_key="#")
        return await canal.declare_queue(
            nombre,
            durable=True,
            arguments={"x-dead-letter-exchange": origen + SUFIJO_DLX},
        )

    async def _publicar(
        self,
        sobre: Dict[str, Any],
        exchange: Optional[aio_pika.abc.AbstractExchange],
        rk: str,
        trace_id: Optional[str],
    ) -> bool:
        if exchange is None:
            return False
        mensaje = aio_pika.Message(
            body=json.dumps(sobre, ensure_ascii=False, default=str).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=sobre.get("event_id"),
            headers={"trace_id": trace_id or "-"},
        )
        try:
            await exchange.publish(mensaje, routing_key=rk, mandatory=True)
            return True
        except Exception as exc:
            log(
                logger,
                logging.WARNING,
                "puente.no_publicado",
                routing_key=rk,
                error=str(exc),
            )
            return False

    async def _procesar_entrante(self, mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            sobre = json.loads(mensaje.body)
        except Exception:
            logger.exception("evento.ilegible")
            await mensaje.reject(requeue=False)  # directo a la DLQ
            return
        token = trace_id_ctx.set(sobre.get("trace_id") or "-")
        try:
            evento = traducir_entrante(sobre)
            if await self._publicar(
                evento.model_dump(mode="json", exclude_none=True),
                self._exchange_eventos,
                evento.event_type,
                evento.trace_id,
            ):
                await mensaje.ack()
            else:
                await mensaje.reject(requeue=False)
        except Exception:
            logger.exception("evento.fallido")
            await mensaje.reject(requeue=False)  # a la DLQ, no bloquea la cola
        finally:
            trace_id_ctx.reset(token)

    async def _procesar_saliente(self, mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            evento = EventoDominio.desde_json(mensaje.body)
        except Exception:
            logger.exception("evento.ilegible")
            await mensaje.reject(requeue=False)  # directo a la DLQ
            return
        token = trace_id_ctx.set(evento.trace_id or "-")
        try:
            if await self._publicar(
                traducir_saliente(evento),
                self._exchange_shipment,
                EVENTO_SALIENTE,
                evento.trace_id,
            ):
                await mensaje.ack()
            else:
                await mensaje.reject(requeue=False)
        except Exception:
            logger.exception("evento.fallido")
            await mensaje.reject(requeue=False)  # a la DLQ, no bloquea la cola
        finally:
            trace_id_ctx.reset(token)

    async def _procesar_telemetria(self, mensaje: aio_pika.abc.AbstractIncomingMessage) -> None:
        """`telemetry.aggregated` propio -> exchange del compañero.

        Diferencia deliberada con las otras dos direcciones: si el mensaje
        resulta NO ENRUTABLE se confirma (ack) y se deja un aviso, en vez de
        mandarlo a la DLQ.

        El motivo es operativo. Que el stack del compañero no esté levantado es
        una situación normal —desarrollamos por separado—, y la telemetría se
        agrega por vehículo cada minuto. Con la política de las otras colas, un
        fin de semana con su stack apagado llenaría la DLQ con miles de
        mensajes idénticos y enterraría los fallos que sí hay que mirar. Un
        agregado perdido no rompe nada: el siguiente llega en 60 segundos y
        trae el acumulado. Una incidencia perdida sí rompe, y por eso esa otra
        cola conserva el comportamiento estricto.
        """
        try:
            evento = EventoDominio.desde_json(mensaje.body)
        except Exception:
            logger.exception("evento.ilegible")
            await mensaje.reject(requeue=False)  # directo a la DLQ
            return

        token = trace_id_ctx.set(evento.trace_id or "-")
        try:
            sobre = traducir_telemetria_saliente(evento)
            if not sobre["datos"].get("vehiculo_id"):
                # Sin vehiculo_id su Maintenance no hace nada con el evento.
                # Se confirma y se avisa: reintentarlo daría el mismo resultado.
                log(
                    logger,
                    logging.WARNING,
                    "telemetria.sin_vehiculo_id",
                    event_id=evento.event_id,
                )
                await mensaje.ack()
                return

            if await self._publicar(
                sobre,
                self._exchange_tracking,
                EVENTO_TELEMETRIA,
                evento.trace_id,
            ):
                await mensaje.ack()
            else:
                log(
                    logger,
                    logging.WARNING,
                    "telemetria.no_entregada",
                    event_id=evento.event_id,
                    detalle="el consumidor del companero no esta escuchando",
                )
                await mensaje.ack()
        except Exception:
            logger.exception("evento.fallido")
            await mensaje.reject(requeue=False)  # a la DLQ, no bloquea la cola
        finally:
            trace_id_ctx.reset(token)

    async def detener(self) -> None:
        self._activo = False
        if self._conexion and not self._conexion.is_closed:
            await self._conexion.close()
