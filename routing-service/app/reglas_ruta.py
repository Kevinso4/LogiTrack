"""Reglas de dominio para construir una ruta viable (secciones 3 y 5).

- Capacidad de carga (kg y m³): restricción dura.
- Ventanas horarias de entrega: restricción dura en esta iteración. Un
  vehículo que no llega dentro de la ventana no es viable.
- Normativa de descanso obligatorio: pausa de 45 min por cada 4,5 h de
  conducción, aplicada sobre la duración bruta del proveedor de mapas.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional


def capacidad_cumplida(
    capacidad_kg: float, capacidad_m3: float, peso_kg: float, volumen_m3: float
) -> bool:
    return capacidad_kg >= peso_kg and capacidad_m3 >= volumen_m3


def pausas_descanso(
    duracion_conduccion_min: float,
    limite_conduccion_min: int = 270,
    pausa_descanso_min: int = 45,
) -> int:
    """Cuántas pausas obligatorias exige el tiempo de conducción.

    Se descansa en los hitos de 270 min que el viaje realmente SUPERA: llegar
    justo al límite no pide pausa; cruzar el límite sí.
    """
    if duracion_conduccion_min <= 0:
        return 0
    return max(0, int((duracion_conduccion_min - 1) // limite_conduccion_min))


def duracion_con_descansos(
    duracion_conduccion_min: float,
    limite_conduccion_min: int = 270,
    pausa_descanso_min: int = 45,
) -> float:
    pausas = pausas_descanso(duracion_conduccion_min, limite_conduccion_min, pausa_descanso_min)
    return duracion_conduccion_min + pausas * pausa_descanso_min


def etas_por_parada(n_paradas: int, inicio: datetime, duracion_total_min: float) -> List[datetime]:
    """Distribuye la duración de la ruta entre las paradas en orden."""
    if n_paradas < 2:
        return []
    fraccion = duracion_total_min / (n_paradas - 1)
    return [inicio + timedelta(minutes=fraccion * i) for i in range(n_paradas)]


def ventana_cumplida_por_todas(
    etas: List[datetime], ventanas_hasta: List[Optional[datetime]]
) -> bool:
    for eta, hasta in zip(etas, ventanas_hasta):
        if hasta is not None and eta > hasta:
            return False
    return True
