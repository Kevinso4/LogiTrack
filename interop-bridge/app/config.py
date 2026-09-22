"""Configuración del Interop Bridge.

Sin base de datos: su única razón de ser es traducir eventos entre el
dialecto de LogiTrack y el del Fleet del compañero (seam 2 del
PROMPT_INTEGRACION). Todo por variables de entorno (12-factor).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identidad del servicio -------------------------------------------
    servicio: str = "interop-bridge"
    version: str = "1.0.0"
    entorno: str = "local"

    # --- bus de eventos ----------------------------------------------------
    bus_habilitado: bool = True
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"
    # Exchange propio, donde LogiTrack ya publica/consume.
    exchange_eventos: str = "logitrack.events"
    # Exchange del compañero: él publica ahí su vehicle.status_changed.
    exchange_fleet: str = "logitrack.fleet"
    # Exchange del compañero: él consume ahí nuestro shipment.incident.
    exchange_shipment: str = "logitrack.shipment"
    # Colas del puente (duraderas, cada una con su DLQ).
    cola_fleet: str = "interop.fleet"
    cola_shipment: str = "interop.shipment"

    # Reintentos del conector del bus: backoff exponencial 1 s → 30 s.
    bus_reintento_base_segundos: float = 1.0
    bus_reintento_maximo_segundos: float = 30.0

    # --- observabilidad ----------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
