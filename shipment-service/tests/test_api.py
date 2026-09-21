"""Pruebas de la API HTTP del Shipment Service."""


async def _crear_via_api(cliente, envio_valido) -> str:
    respuesta = await cliente.post("/api/v1/envios", json=envio_valido)
    assert respuesta.status_code == 201
    return respuesta.json()["id"]


async def test_health_live(cliente):
    respuesta = await cliente.get("/health/live")
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "vivo"


async def test_health_ready(cliente):
    respuesta = await cliente.get("/health/ready")
    assert respuesta.status_code == 200
    assert respuesta.json()["dependencias"]["basedatos"] == "sano"


async def test_crear_envio_via_api(cliente, envio_valido):
    shipment_id = await _crear_via_api(cliente, envio_valido)
    assert len(shipment_id) == 36
    respuesta = await cliente.get(f"/api/v1/envios/{shipment_id}")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "en_almacen"
    assert cuerpo["destino"]["lat"] == 10.96


async def test_envio_inexistente_devuelve_404(cliente):
    respuesta = await cliente.get("/api/v1/envios/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.json()["error"] == "recurso_no_encontrado"


async def test_listar_envios_filtra_por_estado(cliente, envio_valido):
    await _crear_via_api(cliente, envio_valido)
    respuesta = await cliente.get("/api/v1/envios", params={"estado": "en_almacen"})
    assert respuesta.status_code == 200
    assert len(respuesta.json()) == 1
    respuesta = await cliente.get("/api/v1/envios", params={"estado": "entregado"})
    assert respuesta.json() == []


async def test_seguimiento_muestra_solo_lo_del_cliente(cliente, envio_valido):
    shipment_id = await _crear_via_api(cliente, envio_valido)
    respuesta = await cliente.get(f"/api/v1/envios/{shipment_id}/seguimiento")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["shipment_id"] == shipment_id
    assert cuerpo["estado"] == "en_almacen"
    assert "vehicle_id" not in cuerpo  # tipo delgado: nada interno


async def test_historial_registra_la_creacion(cliente, envio_valido):
    shipment_id = await _crear_via_api(cliente, envio_valido)
    respuesta = await cliente.get(f"/api/v1/envios/{shipment_id}/historial")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo) == 1
    assert cuerpo[0]["hasta"] == "en_almacen"


async def test_entregar_via_api(cliente, envio_valido, evento_route_assigned):
    shipment_id = await _crear_via_api(cliente, envio_valido)
    from app.events.base import EventoDominio
    from app.events.manejadores import manejar_evento

    evento_route_assigned["payload"]["shipment_id"] = shipment_id
    await manejar_evento(
        EventoDominio(
            event_id="api-ruta",
            event_type="route.assigned",
            payload=evento_route_assigned["payload"],
        )
    )
    respuesta = await cliente.post(
        f"/api/v1/envios/{shipment_id}/entregar",
        json={"nombre_recibe": "Ana Ruiz", "comentario": "puerta 3"},
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "entregado"


async def test_incidente_via_api_rebota_fuera_de_ruta(cliente, envio_valido):
    shipment_id = await _crear_via_api(cliente, envio_valido)
    respuesta = await cliente.post(
        f"/api/v1/envios/{shipment_id}/incidente",
        json={"tipo": "averia", "confirmado": True},
    )
    assert respuesta.status_code == 422  # en_almacen -> incidente no permitido


async def test_incidente_desde_retrasado_devuelve_422_formato_proyecto(
    cliente, envio_valido, evento_route_assigned, evento_route_unassignable
):
    """Reproducción del bug reportado: en_ruta -> incidente -> retrasado -> incidente."""
    from app.events.base import EventoDominio
    from app.events.manejadores import manejar_evento

    shipment_id = await _crear_via_api(cliente, envio_valido)

    evento_route_assigned["payload"]["shipment_id"] = shipment_id
    await manejar_evento(
        EventoDominio(
            event_id="api-ruta",
            event_type="route.assigned",
            payload=evento_route_assigned["payload"],
        )
    )

    primera = await cliente.post(
        f"/api/v1/envios/{shipment_id}/incidente",
        json={"tipo": "averia", "confirmado": True},
    )
    assert primera.status_code == 200
    assert primera.json()["estado"] == "incidente"

    evento_route_unassignable["payload"]["shipment_id"] = shipment_id
    await manejar_evento(
        EventoDominio(
            event_id="api-sin-ruta",
            event_type="route.unassignable",
            payload=evento_route_unassignable["payload"],
        )
    )

    segunda = await cliente.post(
        f"/api/v1/envios/{shipment_id}/incidente",
        json={"tipo": "averia", "confirmado": True},
    )
    assert segunda.status_code == 422
    cuerpo = segunda.json()
    assert cuerpo["error"] == "regla_negocio"
    assert cuerpo["mensaje"] == "Transición no permitida: retrasado -> incidente"
    assert "trace_id" in cuerpo


async def test_metricas_prometheus(cliente):
    respuesta = await cliente.get("/metrics")
    assert respuesta.status_code == 200
    assert b"shipment_" in respuesta.content
