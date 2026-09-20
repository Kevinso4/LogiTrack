"""Configuración de los tests.

Los tests corren contra SQLite (aiosqlite) y con el bus en memoria: no
necesitan Docker ni PostgreSQL, que es lo que exige el CI de GitHub Actions.
El código de producción no cambia: solo la URL de la base y la implementación
de `PublicadorEventos` (principio de sustitución de Liskov).
"""

import os
import pathlib

RUTA_BD = pathlib.Path(__file__).parent / "fleet_test.db"
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
    async with AsyncClient(transport=transporte, base_url="http://fleet.test") as c:
        yield c


@pytest_asyncio.fixture
async def bus():
    """Publicador en memoria + relay del outbox disparado a mano."""
    publicador = PublicadorEnMemoria()
    await publicador.conectar()
    relay = RelayOutbox(publicador)
    yield publicador, relay


@pytest.fixture
def vehiculo_valido():
    return {
        "plate": "SVK123",
        "type": "refrigerado",
        "capacity_kg": 12000,
        "capacity_m3": 45,
        "year": 2022,
        "insurance_expiry": "2030-12-31",
        "refrigeration_capable": True,
        "hazmat_certified": False,
        "zona": "monteria",
    }


@pytest.fixture
def conductor_valido():
    return {
        "name": "Kevin Ayazo",
        "license_number": "LIC-99001",
        "license_categories": ["C2", "C3"],
        "license_expiry": "2030-01-01",
        "hazmat_certification": False,
        "hours_driven_week": 10,
    }
