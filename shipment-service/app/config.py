"""Configuración del Shipment Service.

Todo se resuelve por variables de entorno (12-factor): el contexto operativo
(producción/Docker) se decide por `ENTORNO`, nunca por banderas mezcladas con
código. El endpoint de demo solo se monta con `DEMO_BUS_INTERNO=true` y fuera
de producción/Docker.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identidad del servicio -------------------------------------------
    servicio: str = "shipment-service"
    version: str = "1.0.0"
    entorno: str = "local"

    # --- persistencia ------------------------------------------------------
    # Database per Service: nadie más lee shipment_db.
    database_url: str = "postgresql+asyncpg://logitrack:logitrack@localhost:5432/shipment_db"
    db_echo: bool = False

    # --- bus de eventos ----------------------------------------------------
    bus_habilitado: bool = True
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"
    exchange_eventos: str = "logitrack.events"
    cola_consumidor: str = "shipment.inbox"
    # Desvío deliberado de la matriz (documentado en el README raíz): además de
    # las rutas se escucha customs.held y customs.cleared para liberar la carga
    # que se traba en aduana.
    eventos_suscritos: List[str] = [
        "route.assigned",
        "route.recalculated",
        "route.unassignable",
        "customs.held",
        "customs.cleared",
    ]

    # Relay del patrón Outbox
    outbox_intervalo_segundos: float = 1.0
    outbox_lote: int = 100
    outbox_max_intentos: int = 10

    # --- reglas de estado del envío ----------------------------------------
    # Cuando el ETA supera el SLA fijado en shipment.created, el envío pasa a
    # "retrasado" y se publica shipment.delayed.
    margen_sla_min: int = 15

    # --- demo / artefactos locales ----------------------------------------
    # Monta /internal/bus/deliver solo en entornos locales de demostración.
    demo_bus_interno: bool = False

    # --- observabilidad ----------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
