"""Tests unitarios de la normalización de unidades y formatos."""

from datetime import datetime, timedelta, timezone

import pytest

from app.normalizacion import (
    ErrorNormalizacion,
    a_celsius,
    distancia_km,
    normalizar,
    obtener_perfil,
)

AHORA = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


def _cruda(**extra):
    base = {
        "vehicle_id": "veh-001",
        "timestamp": AHORA.isoformat(),
        "lat": 8.75,
        "lon": -75.88,
    }
    base.update(extra)
    return base


def test_perfil_generico_no_convierte():
    lectura = normalizar(
        _cruda(velocidad=80, temperatura_motor=90), obtener_perfil(None), ahora=AHORA
    )
    assert lectura.velocidad_kmh == 80
    assert lectura.temperatura_motor_c == 90


def test_perfil_queclink_convierte_mph_y_fahrenheit_y_millas():
    perfil = obtener_perfil("queclink")
    cruda = {
        "latitude": 8.75,
        "longitude": -75.88,
        "time": AHORA.isoformat(),
        "vehicle_id": "veh-001",
        "speed": 60,  # mph
        "engine_temp": 194,  # °F
        "odometer": 100,  # millas
    }
    lectura = normalizar(cruda, perfil, ahora=AHORA)
    assert lectura.velocidad_kmh == pytest.approx(96.561, abs=0.01)
    assert lectura.temperatura_motor_c == pytest.approx(90.0, abs=0.01)
    assert lectura.odometro_km == pytest.approx(160.934, abs=0.01)


def test_perfil_teltonika_renombra_campos_y_pasa_metros_a_km():
    perfil = obtener_perfil("teltonika")
    cruda = {
        "vehicle_id": "veh-002",
        "ts": AHORA.isoformat(),
        "lat": 8.75,
        "lng": -75.88,
        "spd": 45,
        "odo": 250_000,  # metros
        "dtc": "P0128,P0300",
    }
    lectura = normalizar(cruda, perfil, ahora=AHORA)
    assert lectura.lon == -75.88
    assert lectura.velocidad_kmh == 45
    assert lectura.odometro_km == 250.0
    assert lectura.codigos_obd2 == ["P0128", "P0300"]


def test_override_de_unidades_gana_sobre_el_perfil():
    lectura = normalizar(
        _cruda(velocidad=100),
        obtener_perfil("generico"),
        unidades={"velocidad": "mph"},
        ahora=AHORA,
    )
    assert lectura.velocidad_kmh == pytest.approx(160.934, abs=0.01)


def test_combustible_en_fraccion_pasa_a_porcentaje():
    lectura = normalizar(_cruda(combustible=0.63), obtener_perfil("concox"), ahora=AHORA)
    assert lectura.combustible_pct == 63.0


def test_epoch_en_segundos_es_valido():
    lectura = normalizar(_cruda(timestamp=AHORA.timestamp()), obtener_perfil(None), ahora=AHORA)
    assert lectura.timestamp == AHORA


@pytest.mark.parametrize(
    "cruda,motivo",
    [
        ({"timestamp": AHORA.isoformat(), "lat": 8.7, "lon": -75.8}, "campo_faltante"),
        (_cruda(lat=120), "coordenada_invalida"),
        (_cruda(velocidad=400), "velocidad_fuera_de_rango"),
        (_cruda(velocidad="rapido"), "valor_no_numerico"),
        (_cruda(combustible=180), "combustible_fuera_de_rango"),
        (_cruda(timestamp="ayer por la tarde"), "timestamp_invalido"),
    ],
)
def test_lecturas_invalidas_se_rechazan_con_motivo(cruda, motivo):
    with pytest.raises(ErrorNormalizacion) as exc:
        normalizar(cruda, obtener_perfil(None), ahora=AHORA)
    assert exc.value.motivo == motivo


def test_timestamp_futuro_y_antiguo():
    with pytest.raises(ErrorNormalizacion) as futuro:
        normalizar(
            _cruda(timestamp=(AHORA + timedelta(hours=1)).isoformat()),
            obtener_perfil(None),
            ahora=AHORA,
        )
    assert futuro.value.motivo == "timestamp_futuro"

    with pytest.raises(ErrorNormalizacion) as antiguo:
        normalizar(
            _cruda(timestamp=(AHORA - timedelta(days=10)).isoformat()),
            obtener_perfil(None),
            ahora=AHORA,
        )
    assert antiguo.value.motivo == "timestamp_antiguo"


def test_timestamp_sin_zona_se_asume_utc():
    lectura = normalizar(_cruda(timestamp="2026-09-20T12:00:00"), obtener_perfil(None), ahora=AHORA)
    assert lectura.timestamp.tzinfo is timezone.utc


def test_conversion_de_temperatura():
    assert a_celsius(32, "F") == pytest.approx(0.0)
    assert a_celsius(273.15, "K") == pytest.approx(0.0)
    with pytest.raises(ErrorNormalizacion):
        a_celsius(10, "X")


def test_haversine_monteria_cerete():
    # Montería -> Cereté, ~18 km en línea recta.
    km = distancia_km(8.7479, -75.8814, 8.8853, -75.7906)
    assert 15 < km < 22
