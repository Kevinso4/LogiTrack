"""Pruebas de la API HTTP del Routing Service."""

from sqlalchemy import select, update

from app.database import SessionLocal
from app.events.base import EventoDominio
from app.events.manejadores import manejar_evento
from app.models import Ruta


async def _crear_ruta(evento_shipment_created) -> str:
    await manejar_evento(
        EventoDominio(
            event_id="api-evt-1",
            event_type="shipment.created",
            payload=evento_shipment_created["payload"],
        )
    )
    async with SessionLocal() as session:
        return (await session.execute(select(Ruta))).scalars().first().id


async def test_health_live(cliente):
    respuesta = await cliente.get("/health/live")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "vivo"


async def test_health_ready(cliente):
    respuesta = await cliente.get("/health/ready")
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"]["basedatos"] == "sano"


async def test_obtener_ruta_por_id(cliente, evento_shipment_created):
    ruta_id = await _crear_ruta(evento_shipment_created)
    respuesta = await cliente.get(f"/api/v1/rutas/{ruta_id}")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["vehicle_id"] == "v-001"
    assert cuerpo["estado"] == "asignada"
    assert cuerpo["distancia_km"] > 0
    assert cuerpo["eta_actual"] is not None


async def test_ruta_inexistente_devuelve_404(cliente):
    respuesta = await cliente.get("/api/v1/rutas/no-existe")
    assert respuesta.status_code == 404


async def test_ruta_por_shipment(cliente, evento_shipment_created):
    await _crear_ruta(evento_shipment_created)
    respuesta = await cliente.get("/api/v1/rutas/shipment/s-1001")
    assert respuesta.status_code == 200
    assert respuesta.json()["shipment_id"] == "s-1001"


async def test_ruta_por_shipment_inexistente(cliente):
    respuesta = await cliente.get("/api/v1/rutas/shipment/otro-envio")
    assert respuesta.status_code == 404


async def test_recalcular_via_api(cliente, evento_shipment_created, cliente_fleet):
    ruta_id = await _crear_ruta(evento_shipment_created)
    cliente_fleet._vehiculos.append(cliente_fleet._vehiculos[0].model_copy(update={"id": "v-002"}))
    cliente_fleet._vehiculos = [v for v in cliente_fleet._vehiculos if v.id != "v-001"]
    respuesta = await cliente.post(f"/api/v1/rutas/{ruta_id}/recalcular", json={"causa": "test"})
    assert respuesta.status_code == 200
    assert respuesta.json()["vehicle_id"] == "v-002"
    assert respuesta.json()["estado"] == "recalculada"


async def test_navegacion_conductor(cliente, evento_shipment_created):
    await _crear_ruta(evento_shipment_created)
    respuesta = await cliente.get("/api/v1/drivers/navegacion/s-1001")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["shipment_id"] == "s-1001"
    assert len(cuerpo["paradas"]) == 2
    assert cuerpo["paradas"][0]["direccion"] == "Montería"
    assert cuerpo["paradas"][-1]["eta_llegada"] is not None


async def test_navegacion_sin_ruta_devuelve_404(cliente):
    respuesta = await cliente.get("/api/v1/drivers/navegacion/s-inventado")
    assert respuesta.status_code == 404


async def test_estado_rutas_cuenta_por_estado(cliente, evento_shipment_created):
    await _crear_ruta(evento_shipment_created)
    respuesta = await cliente.post("/api/v1/rutas/estado")
    assert respuesta.status_code == 200
    assert respuesta.json()["rutas_por_estado"]["asignada"] == 1


async def test_estado_rutas_con_estado_fuera_del_catalogo(cliente, evento_shipment_created):
    """Defecto 4.1: `por_estado[e] += 1` revienta con KeyError -> 500 si la base
    guarda un estado que no está en el dict (la columna es String(30), admite
    lo que sea: un dato legado, una semilla vieja, una tipeada a mano).
    El health de negocio no debe tumbarse por una fila así: la cuenta igual."""
    ruta_id = await _crear_ruta(evento_shipment_created)
    async with SessionLocal() as session:
        await session.execute(update(Ruta).where(Ruta.id == ruta_id).values(estado="legado"))
        await session.commit()

    respuesta = await cliente.post("/api/v1/rutas/estado")

    assert respuesta.status_code == 200
    assert respuesta.json()["rutas_por_estado"]["legado"] == 1


async def test_metricas_prometheus(cliente):
    respuesta = await cliente.get("/metrics")
    assert respuesta.status_code == 200
    assert b"routing_" in respuesta.content
