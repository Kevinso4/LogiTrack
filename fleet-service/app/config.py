"""Configuración del Fleet Service.

Todo se resuelve por variables de entorno (12-factor). En Render cada valor
llega como env var del servicio; en local se lee de `.env`.
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identidad del servicio -------------------------------------------
    servicio: str = "fleet-service"
    version: str = "1.0.0"
    entorno: str = "local"

    # --- persistencia ------------------------------------------------------
    # Database per Service: nadie más lee fleet_db.
    database_url: str = "postgresql+asyncpg://logitrack:logitrack@localhost:5432/fleet_db"
    db_echo: bool = False

    # --- bus de eventos ----------------------------------------------------
    bus_habilitado: bool = True
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"
    exchange_eventos: str = "logitrack.events"
    cola_consumidor: str = "fleet.inbox"
    eventos_suscritos: List[str] = ["maintenance.alert", "shipment.incident"]

    # Reintentos del conector del bus: backoff exponencial 1 s → 30 s.
    bus_reintento_base_segundos: float = 1.0
    bus_reintento_maximo_segundos: float = 30.0

    # Relay del patrón Outbox
    outbox_intervalo_segundos: float = 1.0
    outbox_lote: int = 100
    outbox_max_intentos: int = 10

    # --- reglas de negocio -------------------------------------------------
    # Normativa de descanso obligatorio: tope semanal de conducción.
    horas_max_conduccion_semana: float = 56.0

    # --- observabilidad ----------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
