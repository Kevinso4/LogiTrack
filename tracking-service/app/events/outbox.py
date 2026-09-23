"""Patrón Outbox: escritura atómica + relay asíncrono hacia el bus.

Registrar el evento es solo un INSERT en la misma transacción del cambio de
negocio. Si el commit falla, no hay evento fantasma; si RabbitMQ está caído,
el evento espera en la tabla y sale cuando el broker vuelve.

El reintento es backoff exponencial, nunca un tope duro: un evento de negocio
no se abandona. `outbox_max_intentos` es un umbral de alarma (log ERROR +
métrica `*_outbox_eventos_agotados_total`), no un límite de reintentos.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal
from app.events.base import EventoDominio, EventoNoRuteable, PublicadorEventos
from app.models import OutboxEvent
from app.observabilidad import eventos_no_entregados, log, outbox_agotados, trace_id_ctx

logger = logging.getLogger(__name__)


def registrar_evento(
    session: AsyncSession,
    event_type: str,
    payload: Dict[str, Any],
    trace_id: Optional[str] = None,
) -> OutboxEvent:
    """Encola un evento dentro de la transacción en curso (NO hace commit)."""
    evento = OutboxEvent(
        event_type=event_type,
        payload=payload,
        trace_id=trace_id or trace_id_ctx.get(),
    )
    session.add(evento)
    return evento


class RelayOutbox:
    """Tarea de fondo: única pieza del servicio que publica en RabbitMQ."""

    def __init__(self, publicador: PublicadorEventos) -> None:
        self._publicador = publicador
        self._settings = get_settings()
        self._tarea: Optional[asyncio.Task] = None
        self._parar = asyncio.Event()

    def iniciar(self) -> None:
        self._parar.clear()
        self._tarea = asyncio.create_task(self._bucle(), name="relay-outbox")

    async def detener(self) -> None:
        self._parar.set()
        if self._tarea:
            self._tarea.cancel()
            try:
                await self._tarea
            except asyncio.CancelledError:
                pass

    async def _bucle(self) -> None:
        while not self._parar.is_set():
            try:
                enviados = await self.despachar_pendientes()
                if enviados == 0:
                    await asyncio.sleep(self._settings.outbox_intervalo_segundos)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox.relay.error")
                await asyncio.sleep(self._settings.outbox_intervalo_segundos * 5)

    def _reprogramar(self, fila: OutboxEvent, motivo: str, ahora: datetime) -> None:
        """Anota el fallo y programa el siguiente intento con backoff exponencial.

        Espera `intervalo * 2^n` (1 s, 2 s, 4 s…) con tope de
        `outbox_espera_maxima_segundos`. Al rebasar `outbox_max_intentos` se
        alarma (log ERROR + métrica) pero SIGUE reintentando: la fila nunca se
        descarta ni se marca como publicada en silencio.
        """
        fila.intentos += 1
        fila.ultimo_error = motivo
        espera = min(
            self._settings.outbox_intervalo_segundos * (2 ** min(fila.intentos - 1, 30)),
            self._settings.outbox_espera_maxima_segundos,
        )
        fila.proximo_intento_en = ahora + timedelta(seconds=espera)
        if fila.intentos >= self._settings.outbox_max_intentos:
            outbox_agotados.inc()
            log(
                logger,
                logging.ERROR,
                "outbox.intentos_agotados",
                event_id=fila.event_id,
                event_type=fila.event_type,
                intentos=fila.intentos,
                reintento_en=fila.proximo_intento_en,
                motivo=motivo,
            )

    async def despachar_pendientes(self) -> int:
        """Publica el siguiente lote de eventos no publicados. Devuelve cuántos."""
        async with SessionLocal() as session:
            ahora = datetime.now(timezone.utc)
            consulta = (
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    # Backoff en vez de tope duro: `proximo_intento_en` NULL es
                    # un evento sin fallos previos (se intenta ya mismo); con
                    # valor, solo toca reintentar cuando el momento vence.
                    or_(
                        OutboxEvent.proximo_intento_en.is_(None),
                        OutboxEvent.proximo_intento_en <= ahora,
                    ),
                )
                .order_by(OutboxEvent.id)
                .limit(self._settings.outbox_lote)
            )
            if session.bind.dialect.name == "postgresql":
                # Varias réplicas del servicio pueden correr el relay a la vez.
                consulta = consulta.with_for_update(skip_locked=True)

            pendientes = (await session.execute(consulta)).scalars().all()
            if not pendientes:
                return 0

            enviados = 0
            for fila in pendientes:
                evento = EventoDominio(
                    event_id=fila.event_id,
                    event_type=fila.event_type,
                    occurred_at=fila.occurred_at,
                    producer=self._settings.servicio,
                    trace_id=fila.trace_id,
                    payload=fila.payload,
                )
                try:
                    await self._publicador.publicar(evento)
                except EventoNoRuteable as exc:  # mandatory: sin cola destino
                    self._reprogramar(fila, exc.motivo[:500], ahora)
                    eventos_no_entregados.labels(fila.event_type, "no_enrutado").inc()
                    log(
                        logger,
                        logging.WARNING,
                        "outbox.evento_no_ruteado",
                        event_id=fila.event_id,
                        event_type=fila.event_type,
                        intentos=fila.intentos,
                        motivo=exc.motivo,
                    )
                    continue
                except Exception as exc:  # broker caído: se reintenta luego
                    self._reprogramar(fila, str(exc)[:500], ahora)
                    eventos_no_entregados.labels(fila.event_type, "conexion").inc()
                    log(
                        logger,
                        logging.WARNING,
                        "outbox.publicacion_fallida",
                        event_id=fila.event_id,
                        event_type=fila.event_type,
                        intentos=fila.intentos,
                    )
                    continue
                fila.published_at = datetime.now(timezone.utc)
                enviados += 1

            await session.commit()
            return enviados
