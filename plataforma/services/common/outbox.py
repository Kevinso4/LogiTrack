"""Patrón Outbox e idempotencia de consumidores.

- `registrar_evento` guarda el evento en `outbox_eventos` dentro de la MISMA transacción
  que el cambio de negocio. Si la transacción falla, el evento no existe; si el broker
  está caído, el evento queda pendiente y se publica al restablecerse.
- `publicador_outbox` es el proceso de fondo que lee la tabla y publica en RabbitMQ.
- `idempotente` envuelve un consumidor: deduplica por `event_id` en `eventos_procesados`,
  en la misma transacción que el efecto del evento.
"""
import asyncio
import logging
import uuid
from datetime import datetime
from typing import Callable

from fastapi.encoders import jsonable_encoder
from sqlalchemy import BigInteger, DateTime, String, Uuid, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.concurrency import run_in_threadpool

from .bus import EventBus
from .db import Base, SessionLocal, ahora

log = logging.getLogger("outbox")


class OutboxEvento(Base):
    __tablename__ = "outbox_eventos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, unique=True)
    agregado_id: Mapped[str] = mapped_column(String(64))
    tipo: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONB)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class EventoProcesado(Base):
    __tablename__ = "eventos_procesados"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(60))
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)


def registrar_evento(db: Session, tipo: str, agregado_id, datos: dict) -> None:
    db.add(OutboxEvento(tipo=tipo, agregado_id=str(agregado_id), payload=jsonable_encoder(datos)))


def _leer_pendientes(limite: int = 100) -> list[OutboxEvento]:
    with SessionLocal() as db:
        return list(
            db.scalars(
                select(OutboxEvento)
                .where(OutboxEvento.publicado_en.is_(None))
                .order_by(OutboxEvento.id)
                .limit(limite)
            )
        )


def _marcar_publicado(evento_id: int) -> None:
    with SessionLocal() as db:
        db.execute(update(OutboxEvento).where(OutboxEvento.id == evento_id).values(publicado_en=ahora()))
        db.commit()


async def publicador_outbox(bus: EventBus, parar: asyncio.Event) -> None:
    while not parar.is_set():
        pendientes: list[OutboxEvento] = []
        try:
            pendientes = await run_in_threadpool(_leer_pendientes)
            for ev in pendientes:
                await bus.publicar(ev.tipo, ev.payload, event_id=str(ev.event_id), ocurrido_en=ev.creado_en)
                await run_in_threadpool(_marcar_publicado, ev.id)
        except Exception:
            log.exception("Fallo publicando la outbox; se reintentará")
            await asyncio.sleep(2)
        if not pendientes:
            await asyncio.sleep(0.5)


def idempotente(fn: Callable[[Session, dict], None]):
    """Convierte `fn(db, evento)` (síncrona) en un handler asíncrono idempotente para el bus."""

    def ejecutar(evento: dict) -> None:
        event_id = uuid.UUID(evento["event_id"])
        with SessionLocal() as db:
            if db.get(EventoProcesado, event_id):
                log.info("Evento %s ya procesado, se descarta", event_id)
                return
            fn(db, evento)
            db.add(EventoProcesado(event_id=event_id, tipo=evento["tipo"]))
            db.commit()

    async def handler(evento: dict) -> None:
        await run_in_threadpool(ejecutar, evento)

    handler.__name__ = fn.__name__
    return handler
