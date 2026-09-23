"""Fleet Service — catálogo maestro de vehículos y conductores.

Responsabilidad única: quién puede mover una carga y en qué estado está.
Arranca tres piezas: la API REST, el relay del outbox y el consumidor del bus.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errores import ErrorAplicacion, manejador_error_aplicacion
from app.events.base import PublicadorEnMemoria, PublicadorEventos
from app.events.manejadores import manejar_evento
from app.events.outbox import RelayOutbox
from app.observabilidad import MiddlewareTrazas, configurar_logging, log
from app.routers import conductores, salud, vehiculos

logger = logging.getLogger(__name__)


def construir_publicador() -> PublicadorEventos:
    """Fábrica del puerto de salida (DIP): RabbitMQ en producción, memoria en tests."""
    settings = get_settings()
    if not settings.bus_habilitado:
        return PublicadorEnMemoria()
    from app.events.rabbitmq import PublicadorRabbitMQ

    return PublicadorRabbitMQ(settings.rabbitmq_url, settings.exchange_eventos)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configurar_logging(settings.log_level)

    publicador = construir_publicador()

    relay = RelayOutbox(publicador)
    relay.iniciar()

    consumidor = None
    conector = None
    if settings.bus_habilitado:
        from app.events.conector import ConectorBus
        from app.events.rabbitmq import ConsumidorRabbitMQ

        consumidor = ConsumidorRabbitMQ(
            url=settings.rabbitmq_url,
            exchange=settings.exchange_eventos,
            cola=settings.cola_consumidor,
            routing_keys=settings.eventos_suscritos,
            manejador=manejar_evento,
        )
        # Reintenta publicador y consumidor con backoff hasta que RabbitMQ
        # acepta la conexión; la tarea vive hasta el shutdown.
        conector = ConectorBus(publicador, consumidor)
        conector.iniciar()

    app.state.publicador = publicador
    app.state.relay = relay
    app.state.conector = conector
    log(logger, logging.INFO, "servicio.arrancado", servicio=settings.servicio)

    yield

    await relay.detener()
    if conector:
        await conector.detener()
    if consumidor:
        await consumidor.detener()
    await publicador.cerrar()
    log(logger, logging.INFO, "servicio.detenido", servicio=settings.servicio)


def crear_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LogiTrack · Fleet Service",
        version=settings.version,
        description=(
            "Maestro de vehículos y conductores. Expone disponibilidad a Routing "
            "y publica `vehicle.status_changed`; consume `maintenance.alert` y "
            "`shipment.incident`."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(MiddlewareTrazas)
    # Orígenes explícitos: frontend en 5173 y panel.html servido en 4173
    # (antes "*" y el origin 'null' del file://). Igual que los otros cuatro.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:4173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ErrorAplicacion, manejador_error_aplicacion)
    app.include_router(salud.router)
    app.include_router(vehiculos.router)
    app.include_router(conductores.router)
    return app


app = crear_app()
