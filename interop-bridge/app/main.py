"""Interop Bridge — punto de entrada del servicio de traducción.

Arranca la API mínima de health checks, el puente sobre RabbitMQ y el
conector que lo reintenta hasta que el bus responde. No hay base de datos;
toda la traducción ocurre en memoria (seam 2 del PROMPT_INTEGRACION).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.observabilidad import configurar_logging, log
from app.salud import router as router_salud

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configurar_logging(settings.log_level)

    puente = None
    conector = None
    if settings.bus_habilitado:
        from app.bus import PuenteRabbitMQ
        from app.conector import ConectorPuente

        puente = PuenteRabbitMQ(settings)
        # Reintenta el puente con backoff hasta que RabbitMQ acepta la
        # conexión; la tarea vive hasta el shutdown.
        conector = ConectorPuente(puente)
        conector.iniciar()

    app.state.puente = puente
    app.state.conector = conector
    log(logger, logging.INFO, "servicio.arrancado", servicio=settings.servicio)

    yield

    if conector:
        await conector.detener()
    if puente:
        await puente.detener()
    log(logger, logging.INFO, "servicio.detenido", servicio=settings.servicio)


def crear_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="LogiTrack · Interop Bridge",
        version=settings.version,
        description=(
            "Traducción bidireccional con el Fleet del compañero: consume "
            "logitrack.fleet (vehicle.status_changed) y publica en "
            "logitrack.events; consume logitrack.events (shipment.incident) "
            "y publica en logitrack.shipment."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(router_salud)
    return app


app = crear_app()
