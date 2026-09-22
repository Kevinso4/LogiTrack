"""Capa anticorrupción hacia el Fleet del compañero.

El compañero habla un dialecto distinto para lo mismo:

  * estados de vehículo: `disponible`, `en_ruta`, `mantenimiento`,
    `fuera_servicio`.
  * campos del vehículo: `placa`, `tipo`, `zona_operacion`, `refrigerado`,
    `certificado_hazmat`.

Este módulo concentra CADA equivalencia de vocabulario (seam 1 y seam 2 del
PROMPT_INTEGRACION). El `routing-service` mantiene un espejo idéntico del
módulo porque cada contenedor corre en su propio filesystem: si cambia una
fila aquí, hay que copiarla allí (los tests de ambos garantizan el mismo
contrato).
"""

from __future__ import annotations

from typing import Dict

# Estados de vehículo en el dialecto propio (Fleet Service) y su equivalente
# en el del compañero. Passthrough: un estado desconocido viaja tal cual, no
# se descarta nunca (mejor una etiqueta rara que un vehículo desaparecido).
ESTADOS_VEHICULO_PROPIOS_A_COMPANERO: Dict[str, str] = {
    "activo": "disponible",
    "en_transito": "en_ruta",
    "en_mantenimiento": "mantenimiento",
    "fuera_de_servicio": "fuera_servicio",
}

ESTADOS_VEHICULO_COMPANERO_A_PROPIOS: Dict[str, str] = {
    v: k for k, v in ESTADOS_VEHICULO_PROPIOS_A_COMPANERO.items()
}

# Estado propio que el algoritmo de asignación interpreta como vehículo listo.
ESTADO_ACTIVO = "activo"

# Campos del vehículo: nombre propio -> nombre del compañero.
CAMPOS_VEHICULO_PROPIOS_A_COMPANERO: Dict[str, str] = {
    "id": "id",
    "plate": "placa",
    "type": "tipo",
    "capacity_kg": "capacidad_kg",
    "capacity_m3": "capacidad_m3",
    "zona": "zona_operacion",
    "refrigeration_capable": "refrigerado",
    "hazmat_certified": "certificado_hazmat",
}


def traducir_estado_vehiculo(estado: str, a_propio: bool = True) -> str:
    """Traduce un estado de vehículo entre dialectos; passthrough si es raro.

    `a_propio=True`: dialecto del compañero -> vocabulario propio
    (disponible -> activo). `a_propio=False`: viceversa (activo -> disponible).
    """
    if estado is None:
        return ""
    tabla = (
        ESTADOS_VEHICULO_COMPANERO_A_PROPIOS if a_propio else ESTADOS_VEHICULO_PROPIOS_A_COMPANERO
    )
    return tabla.get(estado, estado)
