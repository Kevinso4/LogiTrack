"""Sobre común de los eventos (solo lo que necesita el puente).

Mismo formato que `EventoDominio` de los servicios: `{event_id, event_type,
occurred_at, producer, trace_id, payload}`. Aquí se usa como modelo CANÓNICO
interno: el puente lo produce al traducir del compañero y lo consume al
traducir hacia el compañero (documentado en CONTRATOS.md).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class EventoDominio(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    occurred_at: datetime = Field(default_factory=_ahora)
    producer: str = "interop-bridge"
    trace_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def desde_json(cls, datos: bytes) -> "EventoDominio":
        return cls.model_validate(json.loads(datos.decode("utf-8")))
