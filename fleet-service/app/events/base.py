"""Abstracción del bus de eventos (DIP, sección 1.4).

La lógica de negocio depende de `PublicadorEventos`, nunca de aio_pika. Si
mañana el volumen obliga a migrar de RabbitMQ a Kafka, se sustituye la
implementación y el resto del servicio no se entera.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class EventoDominio(BaseModel):
    """Sobre común a todos los eventos del bus de LogiTrack."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    occurred_at: datetime = Field(default_factory=_ahora)
    producer: str = "fleet-service"
    trace_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    def a_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def desde_bytes(cls, datos: bytes) -> "EventoDominio":
        return cls.model_validate(json.loads(datos.decode("utf-8")))


class PublicadorEventos(ABC):
    """Puerto de salida hacia el bus."""

    @abstractmethod
    async def conectar(self) -> None: ...

    @abstractmethod
    async def publicar(self, evento: EventoDominio) -> None: ...

    @abstractmethod
    async def cerrar(self) -> None: ...


class PublicadorEnMemoria(PublicadorEventos):
    """Implementación para tests y para correr sin broker (LSP: mismo contrato)."""

    def __init__(self) -> None:
        self.publicados: List[EventoDominio] = []
        self.conectado = False

    async def conectar(self) -> None:
        self.conectado = True

    async def publicar(self, evento: EventoDominio) -> None:
        self.publicados.append(evento)

    async def cerrar(self) -> None:
        self.conectado = False

    def por_tipo(self, event_type: str) -> List[EventoDominio]:
        return [e for e in self.publicados if e.event_type == event_type]


class EventoNoRuteable(Exception):
    """El broker devolvió el evento (`mandatory`): no había ninguna cola
    suscrita a ese routing key en el exchange.

    Distinguirlo de un fallo de conexión importa al relay del outbox: un
    "no enrutable" no se arregla solo hasta que alguien cree la cola (y habrá
    que reintentar o agotar `outbox_max_intentos`); un fallo de conexión se
    resuelve cuando el broker vuelve. En ambos casos el evento queda PENDIENTE
    (nunca se marca como publicado).
    """

    def __init__(self, event_type: str, motivo: str = "sin cola destino") -> None:
        self.event_type = event_type
        self.motivo = motivo
        super().__init__(f"evento no enrutable ({event_type}): {motivo}")
