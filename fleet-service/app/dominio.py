"""Reglas de dominio del Fleet Service.

El servicio no conoce rutas, envíos ni facturas: solo el catálogo de
vehículos y conductores y su estado operativo (SRP, sección 1.4).
"""

from enum import Enum
from typing import Dict, Set


class EstadoVehiculo(str, Enum):
    ACTIVO = "activo"
    EN_TRANSITO = "en_transito"
    EN_MANTENIMIENTO = "en_mantenimiento"
    FUERA_DE_SERVICIO = "fuera_de_servicio"


class TipoVehiculo(str, Enum):
    FURGON = "furgon"
    TRACTOMULA = "tractomula"
    REFRIGERADO = "refrigerado"
    CISTERNA = "cisterna"
    MOTO = "moto"
    CAMIONETA = "camioneta"


# Máquina de estados: qué transiciones son legales.
# Un vehículo fuera de servicio solo vuelve a operar pasando por taller.
TRANSICIONES: Dict[EstadoVehiculo, Set[EstadoVehiculo]] = {
    EstadoVehiculo.ACTIVO: {
        EstadoVehiculo.EN_TRANSITO,
        EstadoVehiculo.EN_MANTENIMIENTO,
        EstadoVehiculo.FUERA_DE_SERVICIO,
    },
    EstadoVehiculo.EN_TRANSITO: {
        EstadoVehiculo.ACTIVO,
        EstadoVehiculo.EN_MANTENIMIENTO,
        EstadoVehiculo.FUERA_DE_SERVICIO,
    },
    EstadoVehiculo.EN_MANTENIMIENTO: {
        EstadoVehiculo.ACTIVO,
        EstadoVehiculo.FUERA_DE_SERVICIO,
    },
    EstadoVehiculo.FUERA_DE_SERVICIO: {
        EstadoVehiculo.EN_MANTENIMIENTO,
    },
}

# Estados desde los que el vehículo puede aceptar una nueva carga.
ESTADOS_ASIGNABLES = {EstadoVehiculo.ACTIVO}


class TransicionInvalida(Exception):
    def __init__(self, desde: EstadoVehiculo, hacia: EstadoVehiculo):
        self.desde = desde
        self.hacia = hacia
        super().__init__(
            f"Transición no permitida: '{desde.value}' -> '{hacia.value}'. "
            f"Permitidas desde '{desde.value}': "
            + ", ".join(sorted(e.value for e in TRANSICIONES[desde]))
        )


def validar_transicion(desde: EstadoVehiculo, hacia: EstadoVehiculo) -> None:
    if desde == hacia:
        return
    if hacia not in TRANSICIONES[desde]:
        raise TransicionInvalida(desde, hacia)
