"""Tests de la API REST del Fleet Service."""

import pytest


async def test_health_y_ready(cliente):
    assert (await cliente.get("/health")).json()["estado"] == "ok"
    respuesta = await cliente.get("/ready")
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"]["base_datos"] == "ok"


async def test_crear_vehiculo_normaliza_placa(cliente, vehiculo_valido):
    vehiculo_valido["plate"] = "svk-123"
    respuesta = await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["plate"] == "SVK123"
    assert cuerpo["status"] == "activo"


async def test_placa_duplicada_da_409(cliente, vehiculo_valido):
    await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    respuesta = await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    assert respuesta.status_code == 409
    assert respuesta.json()["error"] == "conflicto"


async def test_vehiculo_inexistente_da_404(cliente):
    respuesta = await cliente.get("/api/v1/vehiculos/no-existe")
    assert respuesta.status_code == 404


@pytest.mark.parametrize(
    "parametros,esperados",
    [
        ({"tipo": "refrigerado"}, 1),
        ({"tipo": "furgon"}, 0),
        ({"zona": "monteria"}, 1),
        ({"zona": "bogota"}, 0),
        ({"capacidad_min_kg": 20000}, 0),
        ({"refrigerado": True}, 1),
        ({"hazmat": True}, 0),
    ],
)
async def test_disponibles_aplica_filtros(cliente, vehiculo_valido, parametros, esperados):
    await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    respuesta = await cliente.get("/api/v1/vehiculos/disponibles", params=parametros)
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == esperados


async def test_disponibles_excluye_seguro_vencido(cliente, vehiculo_valido):
    vehiculo_valido["insurance_expiry"] = "2020-01-01"
    await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    respuesta = await cliente.get("/api/v1/vehiculos/disponibles")
    assert respuesta.json() == []


async def test_disponibles_excluye_vehiculo_en_mantenimiento(cliente, vehiculo_valido):
    creado = (await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)).json()
    await cliente.patch(
        f"/api/v1/vehiculos/{creado['id']}/estado",
        json={"estado": "en_mantenimiento", "motivo": "cambio de aceite"},
    )
    assert (await cliente.get("/api/v1/vehiculos/disponibles")).json() == []


async def test_transicion_invalida_da_422(cliente, vehiculo_valido):
    creado = (await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)).json()
    await cliente.patch(
        f"/api/v1/vehiculos/{creado['id']}/estado", json={"estado": "fuera_de_servicio"}
    )
    # fuera_de_servicio -> activo no está permitido: debe pasar por taller.
    respuesta = await cliente.patch(
        f"/api/v1/vehiculos/{creado['id']}/estado", json={"estado": "activo"}
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["error"] == "regla_negocio"


async def test_listado_pagina_y_filtra(cliente, vehiculo_valido):
    await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)
    otro = dict(vehiculo_valido, plate="XYZ987", zona="cerete", type="furgon")
    await cliente.post("/api/v1/vehiculos", json=otro)

    todos = (await cliente.get("/api/v1/vehiculos")).json()
    assert todos["total"] == 2
    solo_cerete = (await cliente.get("/api/v1/vehiculos", params={"zona": "cerete"})).json()
    assert solo_cerete["total"] == 1


async def test_disponibilidad_conductor(cliente, conductor_valido):
    conductor = (await cliente.post("/api/v1/conductores", json=conductor_valido)).json()
    url = f"/api/v1/conductores/{conductor['id']}/disponibilidad"

    disponibilidad = (await cliente.get(url)).json()
    assert disponibilidad["disponible"] is True
    assert disponibilidad["horas_restantes"] == pytest.approx(46.0)

    # Supera el tope semanal de conducción (56 h).
    await cliente.post(f"/api/v1/conductores/{conductor['id']}/horas", json={"horas": 20})
    await cliente.post(f"/api/v1/conductores/{conductor['id']}/horas", json={"horas": 20})
    await cliente.post(f"/api/v1/conductores/{conductor['id']}/horas", json={"horas": 10})

    disponibilidad = (await cliente.get(url)).json()
    assert disponibilidad["disponible"] is False
    assert "tope_horas_semanales_alcanzado" in disponibilidad["motivos"]


async def test_licencia_vencida_bloquea_conductor(cliente, conductor_valido):
    conductor_valido["license_expiry"] = "2020-05-05"
    conductor = (await cliente.post("/api/v1/conductores", json=conductor_valido)).json()
    respuesta = (await cliente.get(f"/api/v1/conductores/{conductor['id']}/disponibilidad")).json()
    assert respuesta["disponible"] is False
    assert "licencia_vencida" in respuesta["motivos"]


async def test_no_asignar_conductor_a_vehiculo_no_operativo(
    cliente, vehiculo_valido, conductor_valido
):
    vehiculo = (await cliente.post("/api/v1/vehiculos", json=vehiculo_valido)).json()
    conductor = (await cliente.post("/api/v1/conductores", json=conductor_valido)).json()
    await cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado", json={"estado": "fuera_de_servicio"}
    )
    respuesta = await cliente.put(
        f"/api/v1/conductores/{conductor['id']}/vehiculo", json={"vehicle_id": vehiculo["id"]}
    )
    assert respuesta.status_code == 422
