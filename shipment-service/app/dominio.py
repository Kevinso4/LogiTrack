"""Reglas de dominio del Shipment Service.

El servicio reina el ciclo de vida del envío de principio a fin (sección 5e):
creación, puesta en ruta, aduana, incidentes, entrega y devolución. Nada más
en LogiTrack conoce esta vida completa; Routing y Fleet solo ven un contratito
de cada evento.
"""

from enum import Enum
from typing import Dict, Set


class EstadoEnvio(str, Enum):
    EN_ALMACEN = "en_almacen"
    EN_RUTA = "en_ruta"
    RETRASADO = "retrasado"
    INCIDENTE = "incidente"
    RETENIDO_ADUANERA = "retenido_aduanera"
    ENTREGADO = "entregado"
    RETORNADO = "retornado"


# Estados cerrados: nada los vuelve a mover.
ESTADOS_FINALES: Set[EstadoEnvio] = {EstadoEnvio.ENTREGADO, EstadoEnvio.RETORNADO}

# Matriz de transiciones permitidas. Modernizar un estado es un caso de
# negocio aparte, no una decisión ad-hoc del controller.
TRANSICIONES: Dict[EstadoEnvio, Set[EstadoEnvio]] = {
    EstadoEnvio.EN_ALMACEN: {
        EstadoEnvio.EN_RUTA,
        EstadoEnvio.RETRASADO,
        EstadoEnvio.RETENIDO_ADUANERA,
    },
    EstadoEnvio.EN_RUTA: {
        EstadoEnvio.RETRASADO,
        EstadoEnvio.INCIDENTE,
        EstadoEnvio.RETENIDO_ADUANERA,
        EstadoEnvio.ENTREGADO,
        EstadoEnvio.RETORNADO,
    },
    EstadoEnvio.RETRASADO: {
        EstadoEnvio.INCIDENTE,
        EstadoEnvio.ENTREGADO,
        EstadoEnvio.RETORNADO,
    },
    EstadoEnvio.INCIDENTE: {
        EstadoEnvio.EN_RUTA,
        EstadoEnvio.RETRASADO,
        EstadoEnvio.RETORNADO,
        EstadoEnvio.ENTREGADO,
    },
    EstadoEnvio.RETENIDO_ADUANERA: {
        EstadoEnvio.EN_RUTA,
        EstadoEnvio.RETRASADO,
        EstadoEnvio.RETORNADO,
    },
    EstadoEnvio.ENTREGADO: set(),
    EstadoEnvio.RETORNADO: set(),
}


def transicion_valida(desde: EstadoEnvio, hasta: EstadoEnvio) -> bool:
    return hasta in TRANSICIONES.get(desde, set())
