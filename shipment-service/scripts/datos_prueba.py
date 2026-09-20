"""Datos de prueba del Shipment Service (demo local sin broker).

Crear un envío vía API REST (la única puerta de creación correcta: publica
shipment.created) y después entregar los eventos de la saga por el endpoint
de demo /internal/bus/deliver.

Uso:
    python scripts/datos_prueba.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8004"

ENVIO_MONTERIA_BARRANQUILLA = {
    "client_id": "cliente-x",
    "origen": {
        "lat": 8.75,
        "lon": -75.88,
        "direccion": "Industrial Las Américas, Montería",
    },
    "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Zona Franca, Barranquilla"},
    "peso_kg": 8000,
    "volumen_m3": 20,
    "is_international": False,
    "requiere_refrigeracion": True,
    "requiere_hazmat": False,
    "ventana_entrega": {
        "desde": "2030-01-15T08:00:00+00:00",
        "hasta": "2030-01-15T20:00:00+00:00",
    },
}

ROUTE_ASSIGNED = {
    "event_type": "route.assigned",
    "payload": {
        "ruta_id": "r-900",
        "vehicle_id": "v-001",
        "vehicle_plate": "SVK123",
        "eta": "2030-01-14T18:30:00+00:00",
        "distancia_km": 650,
        "duracion_min": 1110,
        "tipo_calculo": "calculado",
        "motivo": "asignacion_inicial",
    },
}

ROUTE_UNASSIGNABLE = {
    "event_type": "route.unassignable",
    "payload": {
        "ruta_id": "r-900",
        "motivo": "sin vehículo viable tras el incidente",
        "causa": "shipment.incident",
    },
}

CUSTOMS_HELD = {
    "event_type": "customs.held",
    "payload": {"motivo": "documentación de aduana incompleta"},
}

CUSTOMS_CLEARED = {
    "event_type": "customs.cleared",
    "payload": {"motivo": "documentación completada"},
}


def crear_envio() -> str:
    cuerpo = json.dumps(ENVIO_MONTERIA_BARRANQUILLA).encode("utf-8")
    peticion = urllib.request.Request(
        f"{BASE_URL}/api/v1/envios",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion) as respuesta:
        datos = json.loads(respuesta.read().decode("utf-8"))
        print("POST /api/v1/envios ->", datos["id"], datos["estado"])
        return datos["id"]


def entregar(evento: dict, shipment_id: str) -> None:
    evento["payload"]["shipment_id"] = shipment_id
    cuerpo = json.dumps(evento).encode("utf-8")
    peticion = urllib.request.Request(
        f"{BASE_URL}/internal/bus/deliver",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion) as respuesta:
        print(evento["event_type"], "->", respuesta.read().decode("utf-8"))


if __name__ == "__main__":
    shipment_id = crear_envio()
    entregar(ROUTE_ASSIGNED, shipment_id)
    entregar(ROUTE_UNASSIGNABLE, shipment_id)  # saga: falla -> retrasado + shipment.delayed
    entregar(ROUTE_UNASSIGNABLE, shipment_id)  # misma entrega: idempotente, no duplica
