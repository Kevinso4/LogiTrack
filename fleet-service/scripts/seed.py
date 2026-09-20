"""Carga de datos de prueba del Fleet Service.

Uso:  python scripts/seed.py [--url http://localhost:8001]

Crea una flota pequeña pero variada (refrigerados, hazmat, distintas zonas)
para poder probar de inmediato /api/v1/vehiculos/disponibles.
"""

import argparse
import sys
from datetime import date, timedelta

import httpx

VEHICULOS = [
    {
        "plate": "SVK123",
        "type": "refrigerado",
        "capacity_kg": 12000,
        "capacity_m3": 45,
        "year": 2022,
        "refrigeration_capable": True,
        "hazmat_certified": False,
        "zona": "monteria",
    },
    {
        "plate": "TRM808",
        "type": "tractomula",
        "capacity_kg": 34000,
        "capacity_m3": 90,
        "year": 2020,
        "refrigeration_capable": False,
        "hazmat_certified": True,
        "zona": "monteria",
    },
    {
        "plate": "FRG450",
        "type": "furgon",
        "capacity_kg": 4500,
        "capacity_m3": 18,
        "year": 2023,
        "refrigeration_capable": False,
        "hazmat_certified": False,
        "zona": "cerete",
    },
    {
        "plate": "CIS777",
        "type": "cisterna",
        "capacity_kg": 28000,
        "capacity_m3": 32,
        "year": 2019,
        "refrigeration_capable": False,
        "hazmat_certified": True,
        "zona": "sincelejo",
    },
    {
        "plate": "CAM090",
        "type": "camioneta",
        "capacity_kg": 1200,
        "capacity_m3": 6,
        "year": 2024,
        "refrigeration_capable": False,
        "hazmat_certified": False,
        "zona": "monteria",
    },
]

CONDUCTORES = [
    {
        "name": "Kevin Ayazo",
        "license_number": "LIC-10001",
        "license_categories": ["C2", "C3"],
        "hazmat_certification": True,
        "refrigerated_certification": True,
        "hours_driven_week": 12,
    },
    {
        "name": "Keyner Madrid",
        "license_number": "LIC-10002",
        "license_categories": ["C2"],
        "hazmat_certification": False,
        "refrigerated_certification": True,
        "hours_driven_week": 40,
    },
    {
        "name": "Juan Vega",
        "license_number": "LIC-10003",
        "license_categories": ["C1"],
        "hazmat_certification": False,
        "refrigerated_certification": False,
        "hours_driven_week": 55,
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8001")
    args = parser.parse_args()

    vencimiento = (date.today() + timedelta(days=365)).isoformat()
    creados = []

    with httpx.Client(base_url=args.url, timeout=10) as cliente:
        try:
            cliente.get("/health").raise_for_status()
        except Exception as exc:
            print(f"No se pudo hablar con {args.url}: {exc}")
            return 1

        for vehiculo in VEHICULOS:
            cuerpo = dict(vehiculo, insurance_expiry=vencimiento)
            r = cliente.post("/api/v1/vehiculos", json=cuerpo)
            if r.status_code == 201:
                creados.append(r.json())
                print(f"  vehículo {cuerpo['plate']:<8} -> {r.json()['id']}")
            elif r.status_code == 409:
                print(f"  vehículo {cuerpo['plate']:<8} ya existía")
            else:
                print(f"  ERROR {cuerpo['plate']}: {r.status_code} {r.text}")

        for i, conductor in enumerate(CONDUCTORES):
            cuerpo = dict(
                conductor,
                license_expiry=vencimiento,
                vehicle_id=creados[i]["id"] if i < len(creados) else None,
            )
            r = cliente.post("/api/v1/conductores", json=cuerpo)
            estado = "creado" if r.status_code == 201 else f"{r.status_code}"
            print(f"  conductor {conductor['name']:<16} -> {estado}")

    print("\nListo. Prueba:")
    print(f"  curl '{args.url}/api/v1/vehiculos/disponibles?zona=monteria&refrigerado=true'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
