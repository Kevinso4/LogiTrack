"""Tracking Ingestion Service — el servicio de mayor caudal de LogiTrack.

Una lectura GPS cada 10 s por vehículo: miles de eventos por minuto. Todo el
diseño está puesto al servicio de que la ingesta no se bloquee nunca.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agregador import Agregador
from app.config import get_settings
from app.errores import ErrorAplicacion, manejador_error_aplicacion
from app.events.base import PublicadorEnMemoria, PublicadorEventos
from app.events.outbox import RelayOutbox
from app.observabilidad import MiddlewareTrazas, configurar_logging, log
from app.routers import salud, telemetria

logger = logging.getLogger(__name__)


def construir_publicador() -> PublicadorEventos:
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

    conector = None
    if settings.bus_habilitado:
        from app.events.conector import ConectorBus

        # Tracking solo publica: el conector reintenta el publicador con
        # backoff hasta que RabbitMQ acepta la conexión; vive hasta el shutdown.
        conector = ConectorBus(publicador)
        conector.iniciar()

    agregador = Agregador()
    if settings.agregacion_habilitada:
        agregador.iniciar()

    app.state.publicador = publicador
    app.state.relay = relay
    app.state.conector = conector
    app.state.agregador = agregador
    log(logger, logging.INFO, "servicio.arrancado", servicio=settings.servicio)

    yield

    if settings.agregacion_habilitada:
        await agregador.detener()
    await relay.detener()
    if conector:
        await conector.detener()
    await publicador.cerrar()
    log(logger, logging.INFO, "servicio.detenido", servicio=settings.servicio)


def crear_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LogiTrack · Tracking Ingestion Service",
        version=settings.version,
        description=(
            "Ingesta de telemetría IoT: valida, normaliza unidades entre "
            "fabricantes, persiste en TimescaleDB y publica `telemetry.raw` y "
            "`telemetry.aggregated`. No consume eventos del bus."
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
    app.include_router(telemetria.router)
    return app


app = crear_app()
