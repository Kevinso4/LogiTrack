"""Configuración de los tests del Routing Service.

Los tests corren contra SQLite (aiosqlite), con el bus en memoria y Redis
deshabilitado: no necesitan Docker, PostgreSQL ni un broker. El código de
producción no cambia: solo la URL, la implementación de `PublicadorEventos` y
los adaptadores de Fleet/Mapas/Redis (principio de sustitución de Liskov).
"""

import os
import pathlib

RUTA_BD = pathlib.Path(__file__).parent / "routing_test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{RUTA_BD}"
os.environ["BUS_HABILITADO"] = "false"
os.environ["REDIS_HABILITADO"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.cache_redis import EtaCache  # noqa: E402
from app.cliente_fleet import ClienteFleetFake  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.events.base import PublicadorEnMemoria  # noqa: E402
from app.events.outbox import RelayOutbox  # noqa: E402
from app.main import crear_app  # noqa: E402
from app.proveedores_mapa import SimuladoProveedorMapas  # noqa: E402
from app.schemas import VehiculoDisponible  # noqa: E402
from app.servicios import configurar_adaptadores  # noqa: E402


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


@pytest.fixture
def vehiculo_disponible() -> VehiculoDisponible:
    return VehiculoDisponible(
        id="v-001",
        plate="SVK123",
        type="refrigerado",
        capacity_kg=12000,
        capacity_m3=45,
        zona="monteria",
        refrigeration_capable=True,
        hazmat_certified=False,
    )


@pytest.fixture
def cliente_fleet(vehiculo_disponible) -> ClienteFleetFake:
    return ClienteFleetFake(vehiculos=[vehiculo_disponible])


@pytest_asyncio.fixture(autouse=True)
async def adaptadores(cliente_fleet):
    """Inyecta los fakes (LSP) y los resetea entre tests."""
    cache = EtaCache()
    configurar_adaptadores(
        cliente_fleet=cliente_fleet,
        proveedor_mapa=SimuladoProveedorMapas(),
        cache_eta=cache,
    )
    yield
    await cache.cerrar()


@pytest_asyncio.fixture
async def cliente():
    app = crear_app()
    transporte = ASGITransport(app=app)
    async with AsyncClient(transport=transporte, base_url="http://routing.test") as c:
        yield c


@pytest_asyncio.fixture
async def bus():
    """Publicador en memoria + relay del outbox disparado a mano."""
    publicador = PublicadorEnMemoria()
    await publicador.conectar()
    relay = RelayOutbox(publicador)
    yield publicador, relay


@pytest.fixture
def evento_shipment_created() -> dict:
    return {
        "event_type": "shipment.created",
        "payload": {
            "shipment_id": "s-1001",
            "client_id": "cliente-x",
            "origen": {"lat": 8.75, "lon": -75.88, "direccion": "Montería"},
            "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Barranquilla"},
            "peso_kg": 8000,
            "volumen_m3": 20,
            "is_international": False,
            "sla_deadline": None,
            "requiere_refrigeracion": True,
            "requiere_hazmat": False,
            "ventana_entrega": {
                "desde": "2030-01-15T08:00:00+00:00",
                "hasta": "2030-01-15T20:00:00+00:00",
            },
        },
    }


@pytest.fixture
def evento_telemetry_aggregated() -> dict:
    return {
        "event_type": "telemetry.aggregated",
        "payload": {
            "vehicle_id": "v-001",
            "ventana_inicio": "2026-09-21T10:00:00+00:00",
            "ventana_fin": "2026-09-21T11:00:00+00:00",
            "velocidad_promedio_kmh": 20,
            "detenido": True,
            "ultima_posicion": {"lat": 9.3, "lon": -75.4},
            "distancia_km": 25,
        },
    }


@pytest.fixture
def evento_vehicle_status() -> dict:
    return {
        "event_type": "vehicle.status_changed",
        "payload": {
            "vehicle_id": "v-001",
            "plate": "SVK123",
            "estado_anterior": "activo",
            "estado_nuevo": "fuera_de_servicio",
            "asignable": False,
            "motivo": "incidente en ruta",
            "origen": "shipment.incident",
        },
    }
