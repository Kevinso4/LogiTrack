"""Simulador de dispositivos GPS embarcados.

Cada INTERVALO_SEGUNDOS envía un lote de lecturas a Tracking Ingestion por cada vehículo de la flota:
- vehículos con un envío en tránsito avanzan por la línea origen → destino;
- el resto permanece estacionado en su zona;
- con probabilidad PROB_ANOMALIA inyecta un sobrecalentamiento o un código OBD2 para que
  Maintenance dispare una alerta.
No es parte de la arquitectura de producción: sustituye a los dispositivos IoT reales.
"""
import logging
import math
import os
import random
import time
from datetime import datetime, timezone

import httpx

from common.logs import configurar_logs

configurar_logs("simulator")
log = logging.getLogger("simulator")

FLEET = os.getenv("FLEET_URL", "http://fleet:8000")
TRACKING = os.getenv("TRACKING_URL", "http://tracking:8000")
SHIPMENT = os.getenv("SHIPMENT_URL", "http://shipment:8000")
INTERVALO = float(os.getenv("INTERVALO_SEGUNDOS", "5"))
PROB_ANOMALIA = float(os.getenv("PROB_ANOMALIA", "0.004"))
VELOCIDAD_SIM_KMH = float(os.getenv("VELOCIDAD_SIMULADA_KMH", "900"))  # acelerada para la demo

ZONAS = {
    "montería": (8.7479, -75.8814),
    "cartagena": (10.3910, -75.4794),
    "barranquilla": (10.9685, -74.7813),
    "medellín": (6.2442, -75.5812),
    "sincelejo": (9.3047, -75.3978),
    "santa marta": (11.2408, -74.1990),
    "bogotá": (4.7110, -74.0721),
}
CABECERAS = {"X-User-Role": "servicio"}
CODIGOS_OBD = ["P0217", "P0300", "P0171", "P0420"]


def distancia_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


class Vehiculo:
    def __init__(self, datos: dict):
        self.id = datos["id"]
        self.placa = datos["placa"]
        self.refrigerado = datos["refrigerado"]
        base = ZONAS.get(datos["zona"].lower(), ZONAS["montería"])
        self.pos = (base[0] + random.uniform(-0.02, 0.02), base[1] + random.uniform(-0.02, 0.02))
        self.odometro = random.uniform(8_000, 95_000)
        self.combustible = random.uniform(55, 100)
        self.temp_motor = 85.0
        self.estado = datos["estado"]
        self.clave: str | None = None

    def mover(self, destino: tuple[float, float] | None, dt: float) -> float:
        if not destino or self.estado != "en_transito":
            return 0.0
        restante = distancia_km(self.pos, destino)
        if restante < 0.3:
            return 0.0
        avance = min(restante, VELOCIDAD_SIM_KMH * dt / 3600)
        f = avance / restante
        self.pos = (self.pos[0] + (destino[0] - self.pos[0]) * f, self.pos[1] + (destino[1] - self.pos[1]) * f)
        self.odometro += avance
        self.combustible = max(4.0, self.combustible - avance * 0.02)
        if self.combustible < 12 and random.random() < 0.05:
            self.combustible = 100.0  # repostaje
        return random.uniform(62, 95)

    def lectura(self, velocidad: float) -> dict:
        objetivo = 88 if velocidad > 0 else 70
        self.temp_motor += (objetivo - self.temp_motor) * 0.3 + random.uniform(-1, 1)
        lectura = {
            "vehiculo_id": self.id,
            "registrado_en": datetime.now(timezone.utc).isoformat(),
            "lat": round(self.pos[0], 6),
            "lon": round(self.pos[1], 6),
            "velocidad_kmh": round(velocidad, 1),
            "nivel_combustible": round(self.combustible, 1),
            "temperatura_c": round(random.uniform(2, 5), 1) if self.refrigerado else None,
            "temperatura_motor_c": round(self.temp_motor, 1),
            "odometro_km": round(self.odometro, 1),
            "codigo_obd2": None,
        }
        if self.estado == "en_transito" and random.random() < PROB_ANOMALIA:
            if random.random() < 0.5:
                lectura["temperatura_motor_c"] = round(random.uniform(108, 118), 1)
                log.info("Anomalía inyectada en %s: sobrecalentamiento", self.placa)
            else:
                lectura["codigo_obd2"] = random.choice(CODIGOS_OBD)
                log.info("Anomalía inyectada en %s: código %s", self.placa, lectura["codigo_obd2"])
        return lectura


def esperar(cliente: httpx.Client, url: str) -> None:
    while True:
        try:
            if cliente.get(f"{url}/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        log.info("Esperando a %s ...", url)
        time.sleep(3)


def main() -> None:
    cliente = httpx.Client(timeout=5)
    for url in (FLEET, TRACKING, SHIPMENT):
        esperar(cliente, url)
    flota: dict[str, Vehiculo] = {}
    ultimo = time.monotonic()
    log.info("Simulador iniciado (intervalo %.0fs)", INTERVALO)
    while True:
        time.sleep(INTERVALO)
        ahora = time.monotonic()
        dt, ultimo = ahora - ultimo, ahora
        try:
            vehiculos = cliente.get(f"{FLEET}/api/v1/vehiculos", headers=CABECERAS).json()
            envios = cliente.get(f"{SHIPMENT}/api/v1/envios", params={"estado": "en_transito"},
                                 headers=CABECERAS).json()
            destinos = {e["vehiculo_id"]: (e["destino_lat"], e["destino_lon"]) for e in envios if e["vehiculo_id"]}
            por_clave: dict[str, list[dict]] = {}
            for datos in vehiculos:
                v = flota.get(datos["id"])
                if v is None:
                    v = flota[datos["id"]] = Vehiculo(datos)
                v.estado = datos["estado"]
                if v.clave is None:
                    r = cliente.post(f"{TRACKING}/api/v1/dispositivos", headers=CABECERAS,
                                     json={"vehiculo_id": v.id, "fabricante": "Teltonika FMC130"})
                    r.raise_for_status()
                    v.clave = r.json()["api_key"]
                velocidad = v.mover(destinos.get(v.id), dt)
                por_clave.setdefault(v.clave, []).append(v.lectura(velocidad))
            # Cada dispositivo envía con su propia clave (un lote por vehículo).
            for clave, lecturas in por_clave.items():
                cliente.post(f"{TRACKING}/api/v1/telemetria", json={"lecturas": lecturas},
                             headers={"X-Device-Key": clave}).raise_for_status()
        except Exception as exc:
            log.warning("Ciclo de simulación fallido: %s", exc)


if __name__ == "__main__":
    main()
