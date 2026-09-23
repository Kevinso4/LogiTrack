"""Shipment Service — ciclo de vida del envío.

Responsabilidad única: el envío de principio a fin (creación, ruta, aduana,
incidente, entrega y devolución). Arranca la API REST, el relay del outbox y
el consumidor del bus.

El endpoint `/internal/bus/deliver` es un artefacto de DEMO LOCAL y solo se
monta cuando `DEMO_BUS_INTERNO=true` en un entorno que no sea producción ni
Docker; nunca aparece en docker-compose ni en `.env.example`.
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
from app.routers import bus_interno, envios, salud

logger = logging.getLogger(__name__)

ENTORNOS_DONDE_NO_HAY_BUS_INTERNO = {"produccion", "docker"}


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
        title="LogiTrack · Shipment Service",
        version=settings.version,
        description=(
            "Ciclo de vida del envío. Publica shipment.created/delivered/"
            "incident/returned/delayed; consume route.assigned/recalculated/"
            "unassignable y customs.held/cleared."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(MiddlewareTrazas)
    # Orígenes permitidos: de settings.cors_origins (frontend en 5173, y el
    # panel.html de doble clic que llega como origin "null"). Antes "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ErrorAplicacion, manejador_error_aplicacion)
    app.include_router(salud.router)
    app.include_router(envios.router)

    if settings.demo_bus_interno and settings.entorno not in ENTORNOS_DONDE_NO_HAY_BUS_INTERNO:
        # Artefacto de demostración local: inyecta eventos sin broker.
        app.include_router(bus_interno.router)
        log(
            logger,
            logging.WARNING,
            "demo.bus_interno_montado",
            aviso="endpoint solo para demos; no exponer en producción",
        )
    return app


app = crear_app()
