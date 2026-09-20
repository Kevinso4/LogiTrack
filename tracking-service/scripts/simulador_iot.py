"""Simulador de dispositivos IoT embarcados.

Manda telemetría al Tracking Ingestion Service igual que lo haría el hardware
del vehículo: una lectura cada 10 segundos por vehículo, en lote.

Uso:
    python scripts/simulador_iot.py                       # 3 vehículos sintéticos
    python scripts/simulador_iot.py --fleet-url http://localhost:8001
    python scripts/simulador_iot.py --vehiculos 20 --intervalo 2 --fabricante queclink
"""

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx

# Punto de partida: Montería, Córdoba.
ORIGEN = (8.7479, -75.8814)
CODIGOS_OBD2 = ["P0128", "P0300", "P0420", "P0171"]


class Vehiculo:
    def __init__(self, vehicle_id: str, indice: int):
        self.id = vehicle_id
        self.lat = ORIGEN[0] + random.uniform(-0.05, 0.05)
        self.lon = ORIGEN[1] + random.uniform(-0.05, 0.05)
        self.rumbo = random.uniform(0, 360)
        self.odometro_km = random.uniform(50_000, 200_000)
        self.horas_motor = random.uniform(2_000, 9_000)
        self.combustible = random.uniform(40, 100)
        self.temperatura = random.uniform(80, 92)
        self.indice = indice

    def avanzar(self, segundos: int) -> Dict:
        velocidad_kmh = max(0.0, random.gauss(55, 18))
        distancia_km = velocidad_kmh * segundos / 3600.0
        # Movimiento simple: 1 grado ~ 111 km.
        self.rumbo += random.uniform(-15, 15)
        self.lat += distancia_km / 111.0 * random.uniform(0.2, 1.0)
        self.lon += distancia_km / 111.0 * random.uniform(-1.0, 0.2)
        self.odometro_km += distancia_km
        self.horas_motor += segundos / 3600.0
        self.combustible = max(5.0, self.combustible - distancia_km * 0.05)
        self.temperatura = min(115.0, max(70.0, self.temperatura + random.uniform(-1.5, 1.8)))

        return {
            "vehicle_id": self.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "velocidad": round(velocidad_kmh, 2),
            "temperatura_motor": round(self.temperatura, 2),
            "combustible": round(self.combustible, 2),
            "odometro": round(self.odometro_km, 3),
            "horas_motor": round(self.horas_motor, 2),
            "codigos_obd2": [random.choice(CODIGOS_OBD2)] if random.random() < 0.03 else [],
        }


def convertir_a_fabricante(lectura: Dict, fabricante: str) -> Dict:
    """Devuelve la lectura con los nombres y unidades propios del fabricante."""
    if fabricante == "queclink":  # mph, °F, millas
        return {
            "vehicle_id": lectura["vehicle_id"],
            "time": lectura["timestamp"],
            "latitude": lectura["lat"],
            "longitude": lectura["lon"],
            "speed": round(lectura["velocidad"] / 1.609344, 2),
            "engine_temp": round(lectura["temperatura_motor"] * 9 / 5 + 32, 2),
            "odometer": round(lectura["odometro"] / 1.609344, 3),
            "fuel_level": lectura["combustible"],
            "engine_hours": lectura["horas_motor"],
            "obd_codes": lectura["codigos_obd2"],
        }
    if fabricante == "teltonika":  # metros de odómetro, campos cortos
        return {
            "vehicle_id": lectura["vehicle_id"],
            "ts": lectura["timestamp"],
            "lat": lectura["lat"],
            "lng": lectura["lon"],
            "spd": lectura["velocidad"],
            "tmp": lectura["temperatura_motor"],
            "odo": round(lectura["odometro"] * 1000, 1),
            "fuel": lectura["combustible"],
            "eng_h": lectura["horas_motor"],
            "dtc": ",".join(lectura["codigos_obd2"]),
        }
    return lectura


def obtener_vehiculos(fleet_url: str) -> List[str]:
    with httpx.Client(base_url=fleet_url, timeout=10) as cliente:
        respuesta = cliente.get("/api/v1/vehiculos", params={"limite": 200})
        respuesta.raise_for_status()
        return [v["id"] for v in respuesta.json()["items"]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8002")
    parser.add_argument("--fleet-url", default=None, help="Toma los ids reales del Fleet Service")
    parser.add_argument("--vehiculos", type=int, default=3)
    parser.add_argument("--intervalo", type=int, default=10, help="Segundos entre lotes")
    parser.add_argument("--iteraciones", type=int, default=0, help="0 = infinito")
    parser.add_argument(
        "--fabricante", default="generico", choices=["generico", "queclink", "teltonika"]
    )
    parser.add_argument("--api-key", default=None)
    parser.add_argument(
        "--con-errores",
        action="store_true",
        help="Cuela una lectura corrupta cada tanto para ver los rechazos",
    )
    args = parser.parse_args()

    if args.fleet_url:
        try:
            ids = obtener_vehiculos(args.fleet_url)[: args.vehiculos]
            print(f"Usando {len(ids)} vehículos reales del Fleet Service")
        except Exception as exc:
            print(f"No se pudo leer el Fleet Service ({exc}); uso ids sintéticos")
            ids = []
    else:
        ids = []
    if not ids:
        ids = [f"veh-sim-{i:03d}" for i in range(1, args.vehiculos + 1)]

    flota = [Vehiculo(vid, i) for i, vid in enumerate(ids)]
    cabeceras = {"X-API-Key": args.api_key} if args.api_key else {}

    print(
        f"Enviando a {args.url} cada {args.intervalo}s "
        f"como '{args.fabricante}'. Ctrl+C para parar.\n"
    )
    iteracion = 0
    with httpx.Client(base_url=args.url, timeout=30, headers=cabeceras) as cliente:
        while args.iteraciones == 0 or iteracion < args.iteraciones:
            iteracion += 1
            lecturas = [
                convertir_a_fabricante(v.avanzar(args.intervalo), args.fabricante) for v in flota
            ]
            if args.con_errores and iteracion % 5 == 0:
                lecturas.append({"vehicle_id": "veh-roto", "timestamp": "no-es-fecha"})

            cuerpo = {
                "device_id": "simulador",
                "fabricante": args.fabricante,
                "lecturas": lecturas,
            }
            try:
                respuesta = cliente.post("/api/v1/telemetria", json=cuerpo)
                datos = respuesta.json()
                print(
                    f"#{iteracion:04d} -> {respuesta.status_code} "
                    f"aceptadas={datos.get('aceptadas')} "
                    f"rechazadas={datos.get('rechazadas')} "
                    f"duplicadas={datos.get('duplicadas')} "
                    f"({datos.get('duracion_ms')} ms)"
                )
            except Exception as exc:
                print(f"#{iteracion:04d} -> ERROR: {exc}")

            if args.iteraciones == 0 or iteracion < args.iteraciones:
                time.sleep(args.intervalo)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nSimulador detenido.")
