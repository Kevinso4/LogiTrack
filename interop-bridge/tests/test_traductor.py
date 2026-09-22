"""Tests de la traducción pura del Interop Bridge (seam 2).

Sin red ni RabbitMQ: solo funciones de `app.traductor` y `app.interop`.
Cada test fija la forma EXACTA que el puente publica, para que el compañero
y nosotros sepamos qué esperar (contrato de CONTRATOS.md).
"""

import uuid
from datetime import datetime, timezone

from app.base import EventoDominio
from app.interop import (
    ESTADOS_VEHICULO_COMPANERO_A_PROPIOS,
    traducir_estado_vehiculo,
)
from app.traductor import (
    DATOS_ENTRANTES_A_PROPIOS,
    EVENTO_ENTRANTE,
    EVENTO_SALIENTE,
    PAYLOAD_SALIENTES_A_COMPANERO,
    SOBRE_COMPANERO_A_PROPIOS,
    clave_agregado,
    traducir_datos_entrantes,
    traducir_datos_salientes,
    traducir_entrante,
    traducir_saliente,
)

COMPANERO = {
    "event_id": "ev-1",
    "tipo": "vehicle.status_changed",
    "ocurrido_en": "2026-09-20T13:00:00Z",
    "origen": "companero-fleet",
    "agregado_id": "v-9",
    "datos": {
        "vehiculo_id": "v-9",
        "placa": "COMP-77",
        "estado_anterior": "disponible",
        "estado_nuevo": "en_ruta",
        "motivo": "salio a reparto",
        "zona_operacion": "sur",
    },
}


def test_sobre_comp_a_propio_mapea_campo_a_campo():
    assert SOBRE_COMPANERO_A_PROPIOS == {
        "event_id": "event_id",
        "tipo": "event_type",
        "ocurrido_en": "occurred_at",
        "origen": "producer",
        "datos": "payload",
    }


def test_datos_entrantes_a_propios():
    assert DATOS_ENTRANTES_A_PROPIOS == {
        "vehiculo_id": "vehicle_id",
        "placa": "plate",
        "estado_anterior": "estado_anterior",
        "estado_nuevo": "estado_nuevo",
        "motivo": "motivo",
        "zona_operacion": "zona",
    }


def test_payload_salientes_a_companero():
    assert PAYLOAD_SALIENTES_A_COMPANERO == {
        "vehicle_id": "vehiculo_id",
        "shipment_id": "envio_id",
        "tipo": "tipo",
        "confirmado": "confirmado",
        "motivo": "motivo",
    }


def test_traducir_entrante_conserva_event_id():
    evento = traducir_entrante(COMPANERO, trace_id="t-1")
    assert evento.event_id == "ev-1"
    assert evento.event_type == EVENTO_ENTRANTE
    assert evento.trace_id == "t-1"
    assert evento.producer == "companero-fleet"


def test_traducir_entrante_genera_trace_id_si_no_viene():
    evento = traducir_entrante(COMPANERO)
    assert evento.trace_id is not None
    assert uuid.UUID(evento.trace_id)  # formato uuid4 hex


def test_traducir_entrante_fecha_utc_correcta():
    evento = traducir_entrante(COMPANERO, trace_id="t-1")
    assert evento.occurred_at == datetime(2026, 9, 20, 13, 0, tzinfo=timezone.utc)


def test_traducir_entrante_estados_al_vocabulario_propio():
    evento = traducir_entrante(COMPANERO, trace_id="t-1")
    assert evento.payload["estado_nuevo"] == "en_transito"
    assert evento.payload["estado_anterior"] == "activo"


def test_traducir_entrante_campos_del_payload():
    evento = traducir_entrante(COMPANERO, trace_id="t-1")
    assert evento.payload == {
        "vehicle_id": "v-9",
        "plate": "COMP-77",
        "estado_anterior": "activo",
        "estado_nuevo": "en_transito",
        "motivo": "salio a reparto",
        "zona": "sur",
    }


def test_traducir_saliente_formato_exacto_del_sobre():
    incidente = EventoDominio(
        event_id="ev-2",
        event_type=EVENTO_SALIENTE,
        occurred_at=datetime(2026, 9, 20, 14, 30, tzinfo=timezone.utc),
        producer="shipment-service",
        trace_id="t-2",
        payload={"vehicle_id": "v-9", "shipment_id": "s-5", "tipo": "averia"},
    )
    assert traducir_saliente(incidente) == {
        "event_id": "ev-2",
        "tipo": "shipment.incident",
        "ocurrido_en": "2026-09-20T14:30:00Z",
        "origen": "shipment-service",
        "agregado_id": "s-5",
        "datos": {"vehiculo_id": "v-9", "envio_id": "s-5", "tipo": "averia"},
    }


def test_traducir_saliente_conserva_todo_el_payload_contratado():
    incidente = EventoDominio(
        event_id="ev-3",
        event_type=EVENTO_SALIENTE,
        producer="shipment-service",
        payload={
            "vehicle_id": "v-9",
            "shipment_id": "s-5",
            "confirmado": True,
            "motivo": "pinchazo",
        },
    )
    assert traducir_datos_salientes(incidente.payload) == {
        "vehiculo_id": "v-9",
        "envio_id": "s-5",
        "confirmado": True,
        "motivo": "pinchazo",
    }


def test_clave_agregado_segun_tipo_de_evento():
    assert clave_agregado("shipment.incident", {"shipment_id": "s-1"}) == "s-1"
    assert clave_agregado("vehicle.status_changed", {"vehicle_id": "v-1"}) == "v-1"
    assert clave_agregado("raro.evento", {}) is None


def test_estados_desconocidos_passthrough_en_ambos_dialectos():
    assert traducir_datos_entrantes({"estado_nuevo": "reparando"})["estado_nuevo"] == "reparando"
    assert traducir_estado_vehiculo("raro", a_propio=True) == "raro"
    assert ESTADOS_VEHICULO_COMPANERO_A_PROPIOS == {
        "disponible": "activo",
        "en_ruta": "en_transito",
        "mantenimiento": "en_mantenimiento",
        "fuera_servicio": "fuera_de_servicio",
    }


# ---------------------------------------------------------------------------
# telemetry.aggregated -> exchange del companero (logitrack.tracking)
# ---------------------------------------------------------------------------


def _evento_telemetria(**extra):
    from app.base import EventoDominio

    payload = {
        "vehicle_id": "11111111-1111-1111-1111-111111111111",
        "ventana_inicio": "2026-09-22T14:00:00Z",
        "ventana_fin": "2026-09-22T14:01:00Z",
        "lecturas": 6,
        "velocidad_promedio_kmh": 54.2,
        "velocidad_maxima_kmh": 88.0,
        "temperatura_motor_max_c": 103.5,
        "combustible_pct": 41.0,
        "odometro_km": 82340.5,
        "distancia_km": 0.9,
        "horas_motor": 1920.25,
        "codigos_obd2": ["P0128"],
        "detenido": False,
    }
    payload.update(extra)
    return EventoDominio(
        event_id="evt-telemetria-1",
        event_type="telemetry.aggregated",
        producer="tracking-service",
        trace_id="traza-xyz",
        payload=payload,
    )


def test_telemetria_usa_los_nombres_que_su_maintenance_busca():
    """Los destinos salen del diccionario CAMPOS de su consumidor.

    Si un nombre no coincide, su servicio NO falla: se salta la metrica en
    silencio y la alerta nunca se abre. Por eso se fija con un test.
    """
    from app.traductor import traducir_telemetria_saliente

    datos = traducir_telemetria_saliente(_evento_telemetria())["datos"]
    assert datos["vehiculo_id"] == "11111111-1111-1111-1111-111111111111"
    assert datos["temperatura_max_c"] == 103.5
    assert datos["km_acumulados"] == 82340.5
    assert datos["horas_motor"] == 1920.25
    assert datos["nivel_combustible_pct"] == 41.0


def test_telemetria_no_manda_lo_que_el_no_mira():
    """Velocidades, distancia y OBD2 no entran: su motor de reglas los ignora."""
    from app.traductor import traducir_telemetria_saliente

    datos = traducir_telemetria_saliente(_evento_telemetria())["datos"]
    for sobrante in ("velocidad_maxima_kmh", "distancia_km", "codigos_obd2", "lecturas"):
        assert sobrante not in datos


def test_telemetria_conserva_el_sobre_del_companero():
    from app.traductor import traducir_telemetria_saliente

    sobre = traducir_telemetria_saliente(_evento_telemetria())
    assert set(sobre) == {"event_id", "tipo", "ocurrido_en", "origen", "agregado_id", "datos"}
    assert sobre["tipo"] == "telemetry.aggregated"
    # event_id intacto: es la llave con la que el deduplica.
    assert sobre["event_id"] == "evt-telemetria-1"
    assert sobre["agregado_id"] == "11111111-1111-1111-1111-111111111111"


def test_telemetria_omite_las_metricas_vacias():
    """Un sensor sin lectura manda None; su consumidor hace `continue`."""
    from app.traductor import traducir_telemetria_saliente

    evento = _evento_telemetria(temperatura_motor_max_c=None, combustible_pct=None)
    datos = traducir_telemetria_saliente(evento)["datos"]
    assert "temperatura_max_c" not in datos
    assert "nivel_combustible_pct" not in datos
    assert datos["km_acumulados"] == 82340.5   # el resto sigue viajando
