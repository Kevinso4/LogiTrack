"""Pruebas unitarias de las reglas de ruta (dominio puro): pausas de descanso,
capacidad, ventanas horarias y distribución de ETAs por parada."""

from datetime import datetime, timezone

from app.reglas_ruta import (
    capacidad_cumplida,
    duracion_con_descansos,
    etas_por_parada,
    pausas_descanso,
    ventana_cumplida_por_todas,
)


def test_sin_pausa_si_la_duracion_no_supera_el_limite():
    assert pausas_descanso(180, limite_conduccion_min=270, pausa_descanso_min=45) == 0


def test_una_pausa_al_superar_el_limite():
    assert pausas_descanso(271, limite_conduccion_min=270, pausa_descanso_min=45) == 1


def test_dos_pausas_al_superar_dos_veces_el_limite():
    assert pausas_descanso(560, limite_conduccion_min=270, pausa_descanso_min=45) == 2


def test_duracion_incluye_las_pausas():
    assert duracion_con_descansos(271, 270, 45) == 271 + 45


def test_duracion_cero_no_genera_pausas():
    assert duracion_con_descansos(0, 270, 45) == 0


def test_capacidad_cumplida_cuando_el_vehiculo_soporta_la_carga():
    assert capacidad_cumplida(12000, 45, 8000, 20)


def test_capacidad_no_cumplida_por_kg():
    assert not capacidad_cumplida(7000, 45, 8000, 20)


def test_capacidad_no_cumplida_por_volumen():
    assert not capacidad_cumplida(12000, 10, 8000, 20)


def test_etas_por_parada_equidistantes_en_el_tiempo():
    inicio = datetime(2026, 9, 22, 6, 0, tzinfo=timezone.utc)
    etas = etas_por_parada(3, inicio, 120)
    assert [e.hour for e in etas] == [6, 7, 8]


def test_etas_vacia_para_menos_de_dos_paradas():
    assert etas_por_parada(1, datetime.now(timezone.utc), 60) == []


def test_ventana_cumplida_cuando_todas_las_etas_llegan_a_tiempo():
    hoy = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert ventana_cumplida_por_todas([hoy], [hoy.replace(hour=18)])


def test_ventana_incumplida_con_una_eta_fuera():
    hoy = datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert not ventana_cumplida_por_todas([hoy.replace(hour=19)], [hoy.replace(hour=18)])
