"""Configuración del Tracking Ingestion Service."""

from functools import lru_cache
from typing import List

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Entornos donde el endpoint de telemetría puede quedarse sin claves.
ENTORNOS_DESARROLLO = {"local", "desarrollo"}


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

    # Reintentos del conector del bus: backoff exponencial 1 s → 30 s.
    bus_reintento_base_segundos: float = 1.0
    bus_reintento_maximo_segundos: float = 30.0

    outbox_intervalo_segundos: float = 1.0
    outbox_lote: int = 200
    outbox_max_intentos: int = 10
    # Tope del backoff del relay (1 s, 2 s, 4 s… hasta este tope). Superar
    # outbox_max_intentos solo alarma: el evento sigue reintentando.
    outbox_espera_maxima_segundos: float = 300.0

    # --- ingesta -----------------------------------------------------------
    max_lecturas_por_lote: int = 5000
    # Tolerancia de reloj del dispositivo IoT, en minutos.
    tolerancia_futuro_minutos: int = 5
    antiguedad_maxima_horas: int = 72
    # API keys de los dispositivos embarcados. Vacío = sin autenticación.
    api_keys: List[str] = []

    # --- CORS ---------------------------------------------------------------
    # Orígenes que el navegador puede tocar: de aquí sale allow_origins, que
    # antes era "*" y dejaba cualquier página llamando a la API. "null" es el
    # panel.html abierto con doble clic (file://); configurable por CORS_ORIGINS.
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:4173", "null"]

    @model_validator(mode="after")
    def _exigir_claves_fuera_de_desarrollo(self):
        """No se arranca desplegado abierto por accidente.

        El mecanismo de API key existía pero venía desactivado: api_keys vacío
        por defecto y ningún compose lo definía, mientras la documentación
        afirmaba que la ingesta estaba protegida. Ahora, si no hay claves y el
        entorno no es de desarrollo, el servicio falla al importar la
        configuración — es decir, al arrancar — en vez de salir abierto.
        """
        if not self.api_keys and self.entorno not in ENTORNOS_DESARROLLO:
            raise ValueError(
                f"api_keys vacío en entorno '{self.entorno}': define API_KEYS "
                "o corre en un entorno de desarrollo (local/desarrollo)"
            )
        return self

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
