"""El relay del outbox reintenta con backoff y no abandona eventos.

La consulta filtraba `intentos < outbox_max_intentos`: un tope duro que, a los
diez segundos de RabbitMQ caído, tiraba los eventos pendientes
(`shipment.delivered`…) para siempre. Ahora cada fallo reprograma la fila con
backoff exponencial y, al superar el umbral, solo alarma (log ERROR + métrica)
sin dejar de reintentar.
"""

from datetime import datetime, timedelta, timezone

from prometheus_client import REGISTRY
from sqlalchemy import select  # noqa: F401

from app.config import get_settings
from app.database import SessionLocal
from app.events.base import PublicadorEventos
from app.events.outbox import RelayOutbox, registrar_evento
from app.models import OutboxEvent

METRICA_AGOTADOS = "shipment_outbox_eventos_agotados_total"


class PublicadorRoto(PublicadorEventos):
    """Broker caído: toda publicación revienta con ConnectionError."""

    async def conectar(self) -> None: ...

    async def publicar(self, evento) -> None:
        raise ConnectionError("broker caído")

    async def cerrar(self) -> None: ...


def _a_utc(momento: datetime) -> datetime:
    """SQLite devuelve datetimes naive; en los tests siempre son UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


async def _vencer_backoff(id_fila: int) -> None:
    """Simula que ya pasó la espera: el backoff de la fila queda vencido."""
    async with SessionLocal() as session:
        fila = await session.get(OutboxEvent, id_fila)
        if fila.proximo_intento_en is not None:
            fila.proximo_intento_en = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()


async def test_evento_agotado_sigue_reintentandose_con_backoff():
    """Tras agotar los intentos el evento sigue en la cola, con backoff creciente."""
    settings = get_settings()
    relay = RelayOutbox(PublicadorRoto())

    async with SessionLocal() as session:
        fila = registrar_evento(session, "shipment.delivered", {"shipment_id": "s-1001"})
        await session.commit()
        id_fila = fila.id

    agotados_antes = REGISTRY.get_sample_value(METRICA_AGOTADOS) or 0.0
    esperas: list[timedelta] = []
    total = settings.outbox_max_intentos + 2  # dos intentos MÁS ALLÁ del umbral
    for _ in range(total):
        await _vencer_backoff(id_fila)
        assert await relay.despachar_pendientes() == 0  # nunca pudo publicar
        async with SessionLocal() as session:
            evento = await session.get(OutboxEvent, id_fila)
        esperas.append(_a_utc(evento.proximo_intento_en) - datetime.now(timezone.utc))

    # 1) No se abandona: tras rebasar el umbral sigue siendo seleccionado.
    async with SessionLocal() as session:
        evento = await session.get(OutboxEvent, id_fila)
    assert evento.intentos == total
    assert evento.published_at is None  # sigue PENDIENTE, no descartado en silencio

    # 2) El backoff crece en cada fallo y respeta el tope.
    assert esperas[1] > esperas[0]
    assert esperas[2] > esperas[1]
    assert max(esperas) <= timedelta(seconds=settings.outbox_espera_maxima_segundos + 1)

    # 3) Rebasar el umbral alarma en lugar de callar el evento.
    agotados_despues = REGISTRY.get_sample_value(METRICA_AGOTADOS) or 0.0
    assert agotados_despues > agotados_antes
