"""Reglas de dominio del Routing Service.

El servicio no conoce el ciclo de vida del envío ni la facturación: solo cómo
se construye una ruta viable y en qué estado está (SRP, sección 5e).
"""

from enum import Enum
from typing import Set


class EstadoRuta(str, Enum):
    PENDIENTE = "pendiente"
    ASIGNADA = "asignada"
    RECALCULADA = "recalculada"
    NO_ASIGNABLE = "no_asignable"


# Rutas activas: las únicas que pueden recibir un recálculo.
ESTADOS_ACTIVOS: Set[EstadoRuta] = {EstadoRuta.ASIGNADA, EstadoRuta.RECALCULADA}
