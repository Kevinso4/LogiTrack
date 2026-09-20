"""Configuración del Tracking Ingestion Service."""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identidad ---------------------------------------------------------
    servicio: str = "tracking-service"
    version: str = "1.0.0"
    entorno: str = "local"

    # --- persistencia ------------------------------------------------------
    database_url: str = "postgresql+asyncpg://logitrack:logitrack@localhost:5432/tracking_db"
    db_echo: bool = False
    # TimescaleDB: tamaño del chunk de la hypertable (sección 4 del documento).
    chunk_dias: int = 7
    retencion_dias: int = 0  # 0 = sin política de retención automática

    # --- bus de eventos ----------------------------------------------------
    bus_habilitado: bool = True
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"
    exchange_eventos: str = "logitrack.events"

    outbox_intervalo_segundos: float = 1.0
    outbox_lote: int = 200
    outbox_max_intentos: int = 10

    # --- ingesta -----------------------------------------------------------
    max_lecturas_por_lote: int = 5000
    # Tolerancia de reloj del dispositivo IoT, en minutos.
    tolerancia_futuro_minutos: int = 5
    antiguedad_maxima_horas: int = 72
    # API keys de los dispositivos embarcados. Vacío = sin autenticación (local).
    api_keys: List[str] = []

    # --- agregación --------------------------------------------------------
    agregacion_habilitada: bool = True
    ventana_agregacion_segundos: int = 60
    # Guarda de parseo: por encima de esto la lectura es basura, no un camión.
    velocidad_maxima_kmh: float = 200.0

    # --- observabilidad ----------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
