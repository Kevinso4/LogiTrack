"""Datos de prueba: se cargan solo si la base está vacía."""
from datetime import date

from sqlalchemy import select

from common.db import SessionLocal

from .models import Asignacion, Conductor, ConductorCategoria, TipoVehiculo, Vehiculo

VEHICULOS = [
    ("MTR-101", TipoVehiculo.furgon, "Chevrolet NHR", 2500, 12, 2022, False, False, "Montería"),
    ("MTR-202", TipoVehiculo.camion, "Hino 300", 6000, 30, 2021, True, False, "Montería"),
    ("MTR-303", TipoVehiculo.tractomula, "Kenworth T800", 34000, 90, 2020, False, True, "Montería"),
    ("CTG-404", TipoVehiculo.camion, "Isuzu NPR", 5000, 25, 2023, True, False, "Cartagena"),
    ("CTG-505", TipoVehiculo.van, "Renault Master", 1400, 10, 2024, False, False, "Cartagena"),
    ("BAQ-606", TipoVehiculo.tractomula, "Freightliner M2", 30000, 85, 2019, False, True, "Barranquilla"),
    ("MED-707", TipoVehiculo.furgon, "JAC 1063", 3500, 18, 2022, False, False, "Medellín"),
    ("SIN-808", TipoVehiculo.camion, "Foton Aumark", 4500, 22, 2021, True, False, "Sincelejo"),
]

CONDUCTORES = [
    ("Carlos Pérez", "CC1067845123", "3001234567", False, ["C2"]),
    ("Andrea Gómez", "CC1003456789", "3019876543", True, ["C2", "C3"]),
    ("Luis Martínez", "CC1067111222", "3024567890", True, ["C3"]),
    ("Diana Ríos", "CC1045678901", "3105551234", False, ["C1", "C2"]),
    ("Jorge Salgado", "CC1067333444", "3156667788", False, ["C2"]),
    ("María Hoyos", "CC1102998877", "3187778899", True, ["C3"]),
]


def sembrar() -> None:
    with SessionLocal() as db:
        if db.scalar(select(Vehiculo.id).limit(1)):
            return
        vehiculos = [
            Vehiculo(
                placa=p, tipo=t, marca=m, capacidad_kg=kg, capacidad_m3=m3, anio=a,
                vencimiento_seguro=date(2027, (i % 12) + 1, 15), refrigerado=r, certificado_hazmat=h, zona=z,
            )
            for i, (p, t, m, kg, m3, a, r, h, z) in enumerate(VEHICULOS)
        ]
        conductores = []
        for nombre, lic, tel, hz, cats in CONDUCTORES:
            c = Conductor(nombre=nombre, numero_licencia=lic, telefono=tel, certificacion_hazmat=hz,
                          horas_conducidas_semana=0)
            c.categorias = [ConductorCategoria(categoria=cat) for cat in cats]
            conductores.append(c)
        db.add_all(vehiculos + conductores)
        db.flush()
        # Hay más vehículos que conductores: los 2 últimos quedan sin conductor asignado.
        for v, c in zip(vehiculos, conductores, strict=False):
            db.add(Asignacion(vehiculo_id=v.id, conductor_id=c.id))
        db.commit()
