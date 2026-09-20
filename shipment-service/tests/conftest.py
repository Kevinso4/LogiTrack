"""Configuración de los tests del Shipment Service.

Los tests corren contra SQLite (aiosqlite) y con el bus en memoria: no
necesitan Docker, PostgreSQL ni un broker. El código de producción no cambia:
solo la URL de la base y la implementación de `PublicadorEventos`.
"""

import os
import pathlib

RUTA_BD = pathlib.Path(__file__).parent / "shipment_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{RUTA_BD}"
os.environ["BUS_HABILITADO"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.events.base import PublicadorEnMemoria  # noqa: E402
from app.events.outbox import RelayOutbox  # noqa: E402
from app.main import crear_app  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def preparar_base_datos():
    if RUTA_BD.exists():
        RUTA_BD.unlink()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()
    if RUTA_BD.exists():
        RUTA_BD.unlink()


@pytest_asyncio.fixture(autouse=True)
async def limpiar_tablas():
    async with SessionLocal() as session:
        for tabla in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(tabla))
        await session.commit()
    yield


@pytest_asyncio.fixture
async def cliente():
    app = crear_app()
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://shipment.test") as c:
        yield c


@pytest_asyncio.fixture
async def bus():
    """Publicador en memoria + relay del outbox disparado a mano."""
    publicador = PublicadorEnMemoria()
    await publicador.conectar()
    relay = RelayOutbox(publicador)
    yield publicador, relay


@pytest.fixture
def envio_valido() -> dict:
    return {
        "client_id": "cliente-x",
        "origen": {"lat": 8.75, "lon": -75.88, "direccion": "Montería"},
        "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Barranquilla"},
        "peso_kg": 8000,
        "volumen_m3": 20,
        "is_international": False,
        "requiere_refrigeracion": True,
        "requiere_hazmat": False,
        "ventana_entrega": {
            "desde": "2030-01-15T08:00:00+00:00",
            "hasta": "2030-01-15T20:00:00+00:00",
        },
    }


@pytest.fixture
def envio_internacional(envio_valido) -> dict:
    data = dict(envio_valido)
    data["is_international"] = True
    return data


@pytest.fixture
def evento_route_assigned() -> dict:
    return {
        "event_type": "route.assigned",
        "payload": {
            "ruta_id": "r-900",
            "shipment_id": "s-1001",
            "vehicle_id": "v-001",
            "vehicle_plate": "SVK123",
            "eta": "2030-01-14T18:30:00+00:00",
            "distancia_km": 650,
            "duracion_min": 1110,
            "tipo_calculo": "calculado",
            "motivo": "asignacion_inicial",
        },
    }


@pytest.fixture
def evento_route_unassignable() -> dict:
    return {
        "event_type": "route.unassignable",
        "payload": {
            "ruta_id": "r-900",
            "shipment_id": "s-1001",
            "motivo": "sin vehículo viable",
            "causa": "sin_vehiculo_viable",
        },
    }
