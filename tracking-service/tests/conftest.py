"""Configuración de los tests del Tracking Ingestion Service."""

import os
import pathlib

RUTA_BD = pathlib.Path(__file__).parent / "tracking_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{RUTA_BD}"
os.environ["BUS_HABILITADO"] = "false"
os.environ["AGREGACION_HABILITADA"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

from datetime import datetime, timedelta, timezone  # noqa: E402

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
async def publicador():
    pub = PublicadorEnMemoria()
    await pub.conectar()
    return pub


@pytest_asyncio.fixture
async def cliente(publicador):
    app = crear_app()
    app.state.publicador = publicador  # sin lifespan: se inyecta a mano
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://tracking.test") as c:
        yield c


@pytest_asyncio.fixture
async def relay(publicador):
    return RelayOutbox(publicador)


@pytest.fixture
def ahora():
    return datetime.now(timezone.utc)


@pytest.fixture
def lote_generico(ahora):
    """Tres lecturas de un vehículo moviéndose por Montería."""

    def _crear(vehicle_id: str = "veh-001", n: int = 3, paso_seg: int = 10):
        lecturas = []
        for i in range(n):
            lecturas.append(
                {
                    "vehicle_id": vehicle_id,
                    "timestamp": (ahora - timedelta(seconds=paso_seg * (n - i))).isoformat(),
                    "lat": 8.7500 + i * 0.0050,
                    "lon": -75.8800 + i * 0.0050,
                    "velocidad": 40 + i * 5,
                    "temperatura_motor": 85 + i,
                    "combustible": 70 - i,
                    "odometro": 120_000 + i * 2,
                    "horas_motor": 4200 + i,
                    "codigos_obd2": [],
                }
            )
        return {"device_id": "iot-001", "fabricante": "generico", "lecturas": lecturas}

    return _crear
