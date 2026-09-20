"""Caché de ETAs en Redis con redis.asyncio (sección 4).

Caché OPCIONAL: si Redis está caído, el servicio se sirve de la base y sigue
arriba. Nunca se conecta en el arranque de forma bloqueante; se toca por
llamada y cualquier excepción se degrada a "sin caché".
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from redis.asyncio import Redis as RedisAsync

from app.config import get_settings
from app.observabilidad import log

logger = logging.getLogger(__name__)

PREFIJO = "eta:ruta:"


class EtaCache:
    def __init__(self) -> None:
        settings = get_settings()
        self._habilitado = settings.redis_habilitado
        self._ttl = settings.redis_ttl_eta_segundos
        self._redis: Optional[RedisAsync] = None
        if self._habilitado:
            self._redis = RedisAsync.from_url(settings.redis_url, decode_responses=True)

    async def obtener(self, ruta_id: str) -> Optional[datetime]:
        if self._redis is None:
            return None
        try:
            valor = await self._redis.get(PREFIJO + ruta_id)
            if valor is None:
                return None
            return datetime.fromisoformat(valor)
        except Exception as exc:
            log(logger, logging.DEBUG, "redis.lectura_fallida", error=str(exc))
            return None

    async def guardar(self, ruta_id: str, eta: datetime) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(PREFIJO + ruta_id, eta.isoformat(), ex=self._ttl)
        except Exception as exc:
            log(logger, logging.DEBUG, "redis.escritura_fallida", error=str(exc))

    async def cerrar(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
