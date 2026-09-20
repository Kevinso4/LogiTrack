"""Datos de prueba del Routing Service (demo local sin broker).

Entrega eventos directamente al endpoint /internal/bus/deliver, que monta el
servicio cuando corre con DEMO_BUS_INTERNO=true. Reemplaza al bus de RabbitMQ
en el arranque local (Docker no es obligatorio).

Uso:
    python scripts/datos_prueba.py [base_url]
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8003"

SHIPMENT_MONTERIA_BARRANQUILLA = {
    "event_type": "shipment.created",
    "payload": {
        "shipment_id": "s-1001",
        "client_id": "cliente-x",
        "origen": {"lat": 8.75, "lon": -75.88, "direccion": "Industrial Las Américas, Montería"},
        "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Zona Franca, Barranquilla"},
        "peso_kg": 8000,
        "volumen_m3": 20,
        "is_international": False,
        "sla_deadline": None,
        "requiere_refrigeracion": True,
        "requiere_hazmat": False,
        "ventana_entrega": {
            "desde": "2026-09-22T08:00:00+00:00",
            "hasta": "2026-09-22T20:00:00+00:00",
        },
    },
}

TELEMETRIA_DESVIO = {
    "event_type": "telemetry.aggregated",
    "payload": {
        "vehicle_id": "v-001",
        "ventana_inicio": "2026-09-21T10:00:00+00:00",
        "ventana_fin": "2026-09-21T11:00:00+00:00",
        "lecturas": 12,
        "velocidad_promedio_kmh": 15,
        "velocidad_maxima_kmh": 60,
        "combustible_pct": 62,
        "odometro_km": 89900,
        "distancia_km": 12,
        "ultima_posicion": {"lat": 9.05, "lon": -75.5},
        "detenido": True,
    },
}

VEHICULO_FUERA_SERVICIO = {
    "event_type": "vehicle.status_changed",
    "payload": {
        "vehicle_id": "v-001",
        "plate": "SVK123",
        "estado_anterior": "activo",
        "estado_nuevo": "fuera_de_servicio",
        "asignable": False,
        "motivo": "avería reportada por tracker OBD2",
        "origen": "shipment.incident",
    },
}


def entregar(evento: dict) -> None:
    cuerpo = json.dumps(evento).encode("utf-8")
    peticion = urllib.request.Request(
        f"{BASE_URL}/internal/bus/deliver",
        data=cuerpo,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion) as respuesta:
        print(respuesta.status, respuesta.read().decode("utf-8"))


if __name__ == "__main__":
    print(f"Enviando a {BASE_URL}/internal/bus/deliver")
    entregar(SHIPMENT_MONTERIA_BARRANQUILLA)
    entregar(TELEMETRIA_DESVIO)
    entregar(VEHICULO_FUERA_SERVICIO)
