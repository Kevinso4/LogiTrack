"""Tests de la capa anticorrupción hacia el Fleet del compañero.

Cubren el seam 1 del PROMPT_INTEGRACION: equivalencias de vocabulario en
`app.interop` y los hooks de `ClienteFleetCompanero` (consulta sin
`volumen_min_m3`, respuesta traducida y filtrada). Son unitarios puros: no
tocan red, RabbitMQ ni base.
"""

from app.cliente_fleet import ClienteFleetCompanero, ClienteFleetREST
from app.interop import (
    CAMPOS_VEHICULO_PROPIOS_A_COMPANERO,
    ESTADO_ACTIVO,
    traducir_estado_vehiculo,
)

COMPANERO_DISPONIBLE = {
    "id": "v-1",
    "placa": "ABC-123",
    "tipo": "camion",
    "capacidad_kg": 3000,
    "capacidad_m3": 20,
    "anio": 2022,
    "vencimiento_seguro": "2026-12-31",
    "estado": "disponible",
    "refrigerado": True,
    "certificado_hazmat": False,
    "zona_operacion": "norte",
}


def _cliente() -> ClienteFleetCompanero:
    return ClienteFleetCompanero(base_url="http://companero.test")


def test_campos_mapean_al_dialecto_del_companero():
    assert CAMPOS_VEHICULO_PROPIOS_A_COMPANERO == {
        "id": "id",
        "plate": "placa",
        "type": "tipo",
        "capacity_kg": "capacidad_kg",
        "capacity_m3": "capacidad_m3",
        "zona": "zona_operacion",
        "refrigeration_capable": "refrigerado",
        "hazmat_certified": "certificado_hazmat",
    }


def test_traducir_estado_a_propio():
    assert traducir_estado_vehiculo("disponible", a_propio=True) == "activo"
    assert traducir_estado_vehiculo("en_ruta", a_propio=True) == "en_transito"
    assert traducir_estado_vehiculo("mantenimiento", a_propio=True) == "en_mantenimiento"
    assert traducir_estado_vehiculo("fuera_servicio", a_propio=True) == "fuera_de_servicio"


def test_traducir_estado_a_companero():
    assert traducir_estado_vehiculo("activo", a_propio=False) == "disponible"
    assert traducir_estado_vehiculo("en_transito", a_propio=False) == "en_ruta"
    assert traducir_estado_vehiculo("en_mantenimiento", a_propio=False) == "mantenimiento"
    assert traducir_estado_vehiculo("fuera_de_servicio", a_propio=False) == "fuera_servicio"


def test_traducir_estado_desconocido_es_passthrough():
    assert traducir_estado_vehiculo("reparando", a_propio=True) == "reparando"
    assert traducir_estado_vehiculo("activo", a_propio=True) == "activo"
    assert traducir_estado_vehiculo("", a_propio=True) == ""


def test_consulta_companero_omite_volumen_min_m3():
    params = _cliente()._construir_query(1500, 12.5, refrigerado=True, hazmat=False)
    assert params == {"capacidad_min_kg": 1500, "refrigerado": "true"}


def test_consulta_propia_mantiene_volumen_min_m3():
    params = ClienteFleetREST(base_url="http://fleet.test")._construir_query(
        1500, 12.5, refrigerado=False, hazmat=True
    )
    assert params == {"capacidad_min_kg": 1500, "volumen_min_m3": 12.5, "hazmat": "true"}


def test_parsear_respuesta_traduce_y_filtra_por_volumen():
    chico = dict(COMPANERO_DISPONIBLE, id="v-chico", capacidad_m3=5)
    resultado = _cliente()._parsear_respuesta([COMPANERO_DISPONIBLE, chico], volumen_min_m3=10)
    assert len(resultado) == 1
    assert resultado[0].id == "v-1"


def test_parsear_respuesta_filtra_estados_no_activos():
    sede = dict(COMPANERO_DISPONIBLE, estado="mantenimiento")
    ruta = dict(COMPANERO_DISPONIBLE, id="v-ruta", estado="en_ruta")
    resultado = _cliente()._parsear_respuesta([sede, ruta, COMPANERO_DISPONIBLE], volumen_min_m3=0)
    assert [v.id for v in resultado] == ["v-1"]

    assert _cliente()._parsear_respuesta([ruta], volumen_min_m3=0) == []
    assert _cliente()._parsear_respuesta([sede], volumen_min_m3=0) == []


def test_parsear_respuesta_traduce_campos():
    resultado = _cliente()._parsear_respuesta([COMPANERO_DISPONIBLE], volumen_min_m3=0)
    assert len(resultado) == 1
    vehiculo = resultado[0]
    assert vehiculo.plate == "ABC-123"
    assert vehiculo.type == "camion"
    assert vehiculo.capacity_kg == 3000
    assert vehiculo.capacity_m3 == 20
    assert vehiculo.zona == "norte"
    assert vehiculo.refrigeration_capable is True
    assert vehiculo.hazmat_certified is False
    assert vehiculo.id == "v-1"


def test_estado_activo_clave_de_referencia():
    assert ESTADO_ACTIVO == "activo"
    assert traducir_estado_vehiculo("disponible", a_propio=True) == ESTADO_ACTIVO
