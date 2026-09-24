"""Fábrica de aplicaciones FastAPI: mismo arranque, health checks, logs y bus en todos los servicios."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .bus import EventBus, Handler
from .db import Base, db_ok, engine, esperar_db
from .errores import instalar_manejadores
from .logs import configurar_logs
from .outbox import publicador_outbox

Suscripcion = tuple[str, list[str], Handler]  # (nombre de cola, claves, handler)
Tarea = Callable[[EventBus, asyncio.Event], "asyncio.Future"]


def crear_app(
    nombre: str,
    titulo: str,
    suscripciones: list[Suscripcion] | None = None,
    al_iniciar: Callable[[], None] | None = None,
    tareas: list[Tarea] | None = None,
    usa_outbox: bool = True,
) -> FastAPI:
    configurar_logs(nombre)
    log = logging.getLogger(nombre)
    bus = EventBus(os.environ["RABBITMQ_URL"], nombre)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(esperar_db)
        await run_in_threadpool(Base.metadata.create_all, engine)
        if al_iniciar:
            await run_in_threadpool(al_iniciar)
        await bus.conectar()
        for cola, claves, handler in suscripciones or []:
            await bus.suscribir(f"{nombre}.{cola}", claves, handler)
        parar = asyncio.Event()
        corriendo = []
        if usa_outbox:
            corriendo.append(asyncio.create_task(publicador_outbox(bus, parar)))
        for tarea in tareas or []:
            corriendo.append(asyncio.create_task(tarea(bus, parar)))
        log.info("%s listo", titulo)
        yield
        parar.set()
        for t in corriendo:
            t.cancel()
        await bus.cerrar()

    app = FastAPI(title=titulo, version="1.0.0", lifespan=lifespan)
    app.state.bus = bus
    instalar_manejadores(app)

    @app.get("/health", tags=["salud"])
    def health():
        return {"estado": "vivo", "servicio": nombre}

    @app.get("/ready", tags=["salud"])
    def ready():
        checks = {"base_de_datos": db_ok(), "broker": bus.conectado}
        listo = all(checks.values())
        return JSONResponse(
            {"estado": "listo" if listo else "no_listo", "servicio": nombre, "checks": checks},
            status_code=200 if listo else 503,
        )

    return app
