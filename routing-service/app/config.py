"""Configuración del Routing Service.

Todo se resuelve por variables de entorno (12-factor). El proveedor de mapas y
el cliente de Fleet se configuran por entorno; así cualquier réplica puede
atender cualquier petición (sección 5d del documento: sin estado en memoria).
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- identidad del servicio -------------------------------------------
    servicio: str = "routing-service"
    version: str = "1.0.0"
    entorno: str = "local"

    # --- persistencia ------------------------------------------------------
    # Database per Service: nadie más lee routing_db.
    database_url: str = "postgresql+asyncpg://logitrack:logitrack@localhost:5432/routing_db"
    db_echo: bool = False

    # --- bus de eventos ----------------------------------------------------
    bus_habilitado: bool = True
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"
    exchange_eventos: str = "logitrack.events"
    cola_consumidor: str = "routing.inbox"
    eventos_suscritos: List[str] = [
        "shipment.created",
        "telemetry.aggregated",
        "vehicle.status_changed",
    ]

    # Reintentos del conector del bus: backoff exponencial 1 s → 30 s.
    bus_reintento_base_segundos: float = 1.0
    bus_reintento_maximo_segundos: float = 30.0

    # Relay del patrón Outbox
    outbox_intervalo_segundos: float = 1.0
    outbox_lote: int = 100
    outbox_max_intentos: int = 10
    # Tope del backoff del relay (1 s, 2 s, 4 s… hasta este tope). Superar
    # outbox_max_intentos solo alarma: el evento sigue reintentando.
    outbox_espera_maxima_segundos: float = 300.0

    # --- cliente de Fleet (REST síncrono, camino crítico de asignación) ----
    fleet_url: str = "http://localhost:8001"
    fleet_timeout_segundos: float = 3.0
    fleet_max_reintentos: int = 2
    # Circuit breaker: deja de llamar a Fleet un rato si acumula fallos.
    circuito_errores_antes_de_abrir: int = 3
    circuito_reset_segundos: float = 30.0
    # Dialecto de Fleet: "propio" (nuestro servicio) o "companero" (capa
    # anticorrupción; consulta su REST sin volumen_min_m3 y filtra en memoria).
    fleet_dialecto: str = "propio"

    # --- proveedor de mapas ------------------------------------------------
    # Concentra TODA la dependencia del proveedor de mapas (sección 5g).
    # "simulado" (determinista, dev/demo sin token) o "mapbox".
    proveedor_mapas: str = "simulado"
    mapbox_token: str = ""
    mapbox_url_base: str = "https://api.mapbox.com"

    # --- caché de ETAs (Redis) ---------------------------------------------
    # Caché opcional: si Redis está caído, se sirve de la base y se sigue.
    redis_habilitado: bool = True
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_eta_segundos: int = 300

    # --- reglas de ruta ----------------------------------------------------
    # Estimación lineal de respaldo (sin proveedor) y factor de rotero.
    velocidad_estimacion_kmh: float = 40.0
    factor_rotero: float = 1.3
    # Normativa de descanso obligatorio (EU 561/2006 simplificada).
    limite_conduccion_min: int = 270
    pausa_descanso_min: int = 45
    # Diferencia de ETA que justifica publicar route.recalculated.
    umbral_desvio_min: int = 15

    # --- demo / artefactos locales ----------------------------------------
    # Monta /internal/bus/deliver solo en entornos locales de demostración.
    demo_bus_interno: bool = False

    # --- CORS ---------------------------------------------------------------
    # Orígenes que el navegador puede tocar: de aquí sale allow_origins, que
    # antes era "*" y dejaba cualquier página llamando a la API. Lista
    # explícita (frontend en 5173, panel.html servido en 4173); configurable
    # por CORS_ORIGINS.
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:4173"]

    # --- observabilidad ----------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
