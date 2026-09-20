"""Tests de la API de ingesta, consultas y agregación."""

from datetime import timedelta

from sqlalchemy import func, select

from app.agregador import Agregador
from app.database import SessionLocal
from app.models import OutboxEvent, Telemetry


async def test_health(cliente):
    assert (await cliente.get("/health")).json()["estado"] == "ok"


async def test_ingesta_acepta_lote_y_publica_telemetry_raw(cliente, publicador, lote_generico):
    respuesta = await cliente.post("/api/v1/telemetria", json=lote_generico())
    assert respuesta.status_code == 202
    cuerpo = respuesta.json()
    assert cuerpo["recibidas"] == 3
    assert cuerpo["aceptadas"] == 3
    assert cuerpo["rechazadas"] == 0

    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Telemetry))
    assert total == 3

    eventos = publicador.por_tipo("telemetry.raw")
    assert len(eventos) == 1
    assert eventos[0].payload["conteo"] == 3
    assert eventos[0].payload["vehiculos"] == ["veh-001"]


async def test_lote_parcialmente_invalido_no_tumba_el_resto(cliente, lote_generico):
    lote = lote_generico()
    lote["lecturas"][1]["lat"] = 999  # coordenada imposible
    respuesta = await cliente.post("/api/v1/telemetria", json=lote)

    cuerpo = respuesta.json()
    assert cuerpo["aceptadas"] == 2
    assert cuerpo["rechazadas"] == 1
    assert cuerpo["errores"][0]["motivo"] == "coordenada_invalida"
    assert cuerpo["errores"][0]["indice"] == 1


async def test_reenvio_del_mismo_lote_es_idempotente(cliente, lote_generico):
    lote = lote_generico()
    await cliente.post("/api/v1/telemetria", json=lote)
    segunda = await cliente.post("/api/v1/telemetria", json=lote)

    assert segunda.json()["duplicadas"] == 3
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(Telemetry))
    assert total == 3  # no se duplicó ninguna fila


async def test_normalizacion_en_la_api_con_fabricante_queclink(cliente, ahora):
    lote = {
        "device_id": "iot-77",
        "fabricante": "queclink",
        "lecturas": [
            {
                "vehicle_id": "veh-mph",
                "time": (ahora - timedelta(seconds=5)).isoformat(),
                "latitude": 8.75,
                "longitude": -75.88,
                "speed": 60,
                "engine_temp": 194,
                "odometer": 100,
            }
        ],
    }
    assert (await cliente.post("/api/v1/telemetria", json=lote)).status_code == 202

    ultima = (await cliente.get("/api/v1/telemetria/veh-mph/ultima")).json()
    assert round(ultima["speed_kmh"], 1) == 96.6
    assert round(ultima["engine_temp_c"], 1) == 90.0
    assert round(ultima["odometer_km"], 1) == 160.9


async def test_lote_vacio_es_rechazado_por_validacion(cliente):
    respuesta = await cliente.post("/api/v1/telemetria", json={"lecturas": []})
    assert respuesta.status_code == 422


async def test_ultima_sin_datos_da_404(cliente):
    assert (await cliente.get("/api/v1/telemetria/fantasma/ultima")).status_code == 404


async def test_recorrido_calcula_distancia_y_velocidades(cliente, lote_generico, ahora):
    await cliente.post("/api/v1/telemetria", json=lote_generico(n=4))
    respuesta = await cliente.get(
        "/api/v1/telemetria/veh-001/recorrido",
        params={
            "desde": (ahora - timedelta(hours=1)).isoformat(),
            "hasta": ahora.isoformat(),
        },
    )
    cuerpo = respuesta.json()
    assert cuerpo["lecturas"] == 4
    assert cuerpo["distancia_km"] > 0
    assert cuerpo["velocidad_maxima_kmh"] == 55
    assert len(cuerpo["puntos"]) == 4


async def test_agregacion_publica_telemetry_aggregated(cliente, publicador, relay, lote_generico):
    await cliente.post("/api/v1/telemetria", json=lote_generico(vehicle_id="veh-A", n=3))
    await cliente.post("/api/v1/telemetria", json=lote_generico(vehicle_id="veh-B", n=2))

    agregados = await Agregador(ventana_segundos=300).ejecutar_ventana()
    assert {a.vehicle_id for a in agregados} == {"veh-A", "veh-B"}

    agregado_a = next(a for a in agregados if a.vehicle_id == "veh-A")
    assert agregado_a.lecturas == 3
    assert agregado_a.velocidad_maxima_kmh == 50
    assert agregado_a.distancia_km > 0
    assert agregado_a.ultima_posicion is not None

    # Los eventos quedan en el outbox hasta que el relay los publica.
    async with SessionLocal() as session:
        pendientes = (
            (await session.execute(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))))
            .scalars()
            .all()
        )
    assert len(pendientes) == 2

    assert await relay.despachar_pendientes() == 2
    publicados = publicador.por_tipo("telemetry.aggregated")
    assert len(publicados) == 2
    assert publicados[0].producer == "tracking-service"


async def test_agregacion_sin_datos_no_publica_nada(relay):
    assert await Agregador(ventana_segundos=60).ejecutar_ventana() == []
    assert await relay.despachar_pendientes() == 0


async def test_lote_demasiado_grande_es_rechazado(cliente, lote_generico, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_lecturas_por_lote", 2)
    respuesta = await cliente.post("/api/v1/telemetria", json=lote_generico(n=3))
    assert respuesta.status_code == 422
    assert respuesta.json()["error"] == "regla_negocio"
