"""Tracking Ingestion Service — el servicio de mayor caudal de LogiTrack.

Una lectura GPS cada 10 s por vehículo: miles de eventos por minuto. Todo el
diseño está puesto al servicio de que la ingesta no se bloquee nunca.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

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
    try:
        await publicador.conectar()
    except Exception as exc:
        log(logger, logging.WARNING, "bus.conexion_diferida", error=str(exc))

    relay = RelayOutbox(publicador)
    relay.iniciar()

    agregador = Agregador()
    if settings.agregacion_habilitada:
        agregador.iniciar()

    app.state.publicador = publicador
    app.state.relay = relay
    app.state.agregador = agregador
    log(logger, logging.INFO, "servicio.arrancado", servicio=settings.servicio)

    yield

    if settings.agregacion_habilitada:
        await agregador.detener()
    await relay.detener()
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
    app.add_exception_handler(ErrorAplicacion, manejador_error_aplicacion)
    app.include_router(salud.router)
    app.include_router(telemetria.router)
    return app


app = crear_app()
