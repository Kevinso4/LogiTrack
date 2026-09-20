"""Saga del incidente reproducida punta a punta en local, sin Docker ni broker.

Levanta Fleet (8001), Routing (8003) y Shipment (8004) como subprocesos
uvicorn separados con SQLite y `BUS_HABILITADO=false`, y hace de orquestador:
drena la tabla `outbox_events` de cada sqlite y entrega cada evento por
`POST /internal/bus/deliver` al consumidor correcto, igual que haría RabbitMQ.

La reacción de Fleet al `shipment.incident` no tiene endpoint interno, así que
la emula por su REST (`PATCH /vehiculos/{id}/estado -> fuera_de_servicio`), que
es exactamente lo que haría su consumidor, y el `vehicle.status_changed` que
produce viaja después por el outbox real.

Uso:   .venv\\Scripts\\python demo\\saga_demo.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable

# nombre -> (cwd, puerto, sqlite, ruta de health)
SERVICIOS = {
    "fleet": ("fleet-service", 8001, "fleet_demo.db", "/health"),
    "routing": ("routing-service", 8003, "routing_demo.db", "/health/live"),
    "shipment": ("shipment-service", 8004, "shipment_demo.db", "/health/live"),
}

# A quién se entrega cada evento producido (routing key == event_type).
DESTINO = {
    "shipment.created": "routing",
    "vehicle.status_changed": "routing",
    "route.assigned": "shipment",
    "route.recalculated": "shipment",
    "route.unassignable": "shipment",
    "shipment.incident": "fleet",  # se emula por REST (Fleet no tiene bus interno)
    "shipment.delayed": None,  # terminal: solo se reporta
}

VENTANA = {"desde": "2030-01-15T08:00:00+00:00", "hasta": "2030-01-15T20:00:00+00:00"}

VEHICULO = {
    "plate": "SVK123",
    "type": "refrigerado",
    "capacity_kg": 12000,
    "capacity_m3": 45,
    "year": 2022,
    "refrigeration_capable": True,
    "hazmat_certified": False,
    "zona": "monteria",
    "insurance_expiry": "2035-01-01",
}

ENVIO = {
    "client_id": "cliente-x",
    "origen": {"lat": 8.75, "lon": -75.88, "direccion": "Industrial Las Américas, Montería"},
    "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Zona Franca, Barranquilla"},
    "peso_kg": 8000,
    "volumen_m3": 20,
    "is_international": False,
    "requiere_refrigeracion": True,
    "requiere_hazmat": False,
    "ventana_entrega": VENTANA,
}

ANSI_VERDE = "\033[92m"
ANSI_CYAN = "\033[96m"
ANSI_ROJO = "\033[91m"
ANSI_FIN = "\033[0m"

procesos: list[subprocess.Popen] = []
consume_anterior: dict[str, int] = {}  # último id drenado por servicio


# ---------------------------------------------------------------------------
# Helpers HTTP (stdlib).
# ---------------------------------------------------------------------------
def http(method: str, url: str, cuerpo=None, timeout: float = 10.0):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
    peticion = urllib.request.Request(
        url,
        data=datos,
        method=method,
        headers={"Content-Type": "application/json"} if cuerpo is not None else {},
    )
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        texto = respuesta.read().decode("utf-8")
        return respuesta.status, json.loads(texto) if texto else None


def esperar_health(nombre: str, segundos: float = 90.0) -> None:
    _, puerto, _, ruta = SERVICIOS[nombre]
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            estado, _ = http("GET", f"http://localhost:{puerto}{ruta}", timeout=2)
            if estado == 200:
                print(f"  {nombre:9} :800{puerto % 10} listo")
                return
        except OSError:
            time.sleep(0.5)
    print(f"{ANSI_ROJO}FATAL{ANSI_FIN}: {nombre} no levantó a tiempo")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Outbox: leer pendientes del sqlite del servicio y entregarlos.
# ---------------------------------------------------------------------------
def pendientes(nombre: str):
    cwd, puerto, bd, _ = SERVICIOS[nombre]
    ruta = os.path.join(RAIZ, cwd, bd)
    ultimo = consume_anterior.get(nombre, 0)
    conn = sqlite3.connect(ruta, timeout=10)
    try:
        filas = conn.execute(
            "SELECT id, event_id, event_type, payload FROM outbox_events WHERE id > ? ORDER BY id",
            (ultimo,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": f[0], "event_id": f[1], "event_type": f[2], "payload": json.loads(f[3])}
        for f in filas
    ]


def entregar(nombre: str, fila: dict) -> None:
    destino = DESTINO.get(fila["event_type"])
    if destino is None:
        print(
            f"  {ANSI_VERDE}{fila['event_type']:<26}{ANSI_FIN} (terminal, pendiente en el outbox)"
        )
        return
    cwd, puerto, bd, _ = SERVICIOS[destino]
    if destino == "fleet":
        # Fleet no expone bus interno: la reacción se emula por su REST real.
        vehicle_id = fila["payload"].get("vehicle_id") or fila["payload"].get("vehiculo_id")
        http(
            "PATCH",
            f"http://localhost:{puerto}/api/v1/vehiculos/{vehicle_id}/estado",
            {
                "estado": "fuera_de_servicio",
                "motivo": fila["payload"].get("motivo") or f"saga: {fila['event_type']}",
            },
        )
        print(f"  {fila['event_type']:<26} -> fleet PATCH fuera_de_servicio (emulado)")
        return
    cuerpo = {
        "event_id": fila["event_id"],
        "event_type": fila["event_type"],
        "producer": destino,
        "payload": fila["payload"],
    }
    try:
        estado, _ = http("POST", f"http://localhost:{puerto}/internal/bus/deliver", cuerpo)
        assert estado == 200
    except AssertionError:
        print(f"{ANSI_ROJO}ERROR{ANSI_FIN} entregando {fila['event_type']} a {destino}")
        raise


def drenar_y_entregar(nombre: str, tipo_esperado=None, segundos: float = 60.0) -> list:
    """Espera `tipo_esperado` en el outbox de `nombre` y despacha todo lo que aparezca."""
    limite = time.time() + segundos
    candidatos = []
    while time.time() < limite:
        pendientes_ahora = pendientes(nombre)
        if tipo_esperado is None or any(f["event_type"] == tipo_esperado for f in pendientes_ahora):
            candidatos = pendientes_ahora
            break
        time.sleep(0.3)
    else:
        print(f"{ANSI_ROJO}FATAL{ANSI_FIN}: {nombre} nunca emitió {tipo_esperado}")
        _diagnostico(nombre)
        sys.exit(1)

    entregados = []
    for fila in candidatos:
        entregar(nombre, fila)
        entregados.append(fila)
        consume_anterior[nombre] = max(consume_anterior.get(nombre, 0), fila["id"])
    if tipo_esperado is None and not candidatos:
        pass
    return [f["event_type"] for f in entregados]


# ---------------------------------------------------------------------------
# Puesta en escena.
# ---------------------------------------------------------------------------
def _diagnostico(nombre: str) -> None:
    cwd, _, bd, _ = SERVICIOS[nombre]
    ruta = os.path.join(RAIZ, cwd, bd)
    conn = sqlite3.connect(ruta, timeout=10)
    try:
        print("  consumo:", consume_anterior)
        print("  outbox:")
        for fila in conn.execute("SELECT id, event_type, event_id FROM outbox_events ORDER BY id"):
            print(f"    #{fila[0]} {fila[1]:<26} {fila[2]}")
        print("  procesados:")
        for eid, tipo in conn.execute("SELECT event_id, event_type FROM processed_events"):
            print(f"    {tipo:<26} {eid}")
    finally:
        conn.close()
    log = os.path.join(os.environ.get("TEMP", RAIZ), f"logitrack-{nombre}.log")
    if os.path.exists(log):
        print(f"  ---- cola del log ({log}) ----")
        with open(log, encoding="utf-8", errors="replace") as fh:
            print("".join(fh.readlines()[-40:]))


def migrar(cwd: str, url_bd: str) -> None:
    subprocess.run(
        [PYTHON, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.join(RAIZ, cwd),
        env={**os.environ, "DATABASE_URL": url_bd, "BUS_HABILITADO": "false"},
        check=True,
        capture_output=True,
    )


def arrancar(nombre: str) -> None:
    cwd, puerto, bd, _ = SERVICIOS[nombre]
    ruta_bd = os.path.join(RAIZ, cwd, bd).replace("\\", "/")
    entorno = {
        **os.environ,
        "DATABASE_URL": f"sqlite+aiosqlite:///{ruta_bd}",
        "BUS_HABILITADO": "false",
        "ENTORNO": "local",
        "LOG_LEVEL": "WARNING",
        "DEMO_BUS_INTERNO": "true",
    }
    if nombre == "routing":
        entorno.update(
            FLEET_URL="http://localhost:8001", PROVEEDOR_MAPAS="simulado", REDIS_HABILITADO="false"
        )
    comando = [
        PYTHON,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(puerto),
        "--no-access-log",
    ]
    procesos.append(
        subprocess.Popen(
            comando,
            cwd=os.path.join(RAIZ, cwd),
            env=entorno,
            stdout=subprocess.DEVNULL,
            stderr=open(os.path.join(os.environ.get("TEMP", RAIZ), f"logitrack-{nombre}.log"), "w"),
        )
    )


def detener() -> None:
    for p in procesos:
        p.terminate()


def main() -> int:
    try:
        print(f"{ANSI_CYAN}>> SAGA DEL INCIDENTE (sin Docker, sin broker){ANSI_FIN}")
        for nombre, (cwd, _, bd, _) in SERVICIOS.items():
            ruta = os.path.join(RAIZ, cwd, bd)
            if os.path.exists(ruta):
                os.remove(ruta)
        print("Migrando esquemas...")
        for nombre in SERVICIOS:
            cwd, _, bd, _ = SERVICIOS[nombre]
            migrar(cwd, f"sqlite+aiosqlite:///{os.path.join(RAIZ, cwd, bd).replace(chr(92), '/')}")

        print("Arrancando servicios...")
        for nombre in SERVICIOS:
            arrancar(nombre)
        for nombre in SERVICIOS:
            esperar_health(nombre)

        print("\n1. Alta del vehículo de la flota")
        _, vh = http("POST", "http://localhost:8001/api/v1/vehiculos", VEHICULO)
        vehicle_id = vh["id"]
        print(f"   vehículo {VEHICULO['plate']} -> {vehicle_id}")

        print("\n2. Alta del envío (refrigerado, Montería -> Barranquilla)")
        _, envio = http("POST", "http://localhost:8004/api/v1/envios", ENVIO)
        shipment_id = envio["id"]
        print(f"   shipment {shipment_id} -> {envio['estado']}")

        print("\n3. shipment.created viaja por el outbox -> Routing asigna SVK123")
        drenar_y_entregar("shipment", "shipment.created")
        evento = next(e for e in pendientes("routing") if e["event_type"] == "route.assigned")
        ruta_id = evento["payload"]["ruta_id"]
        print(f"   Routing creó la ruta {ruta_id}")

        print("\n4. route.assigned -> Shipment pone el envío en ruta")
        drenar_y_entregar("routing", "route.assigned")
        _, seg = http("GET", f"http://localhost:8004/api/v1/envios/{shipment_id}/seguimiento")
        print(f"   estado: {ANSI_VERDE}{seg['estado']}{ANSI_FIN}, ETA {seg.get('eta')}")

        print("\n5. Incidente crítico: la carga se queda varada (avería confirmada)")
        http(
            "POST",
            f"http://localhost:8004/api/v1/envios/{shipment_id}/incidente",
            {"tipo": "averia", "confirmado": True, "motivo": "tren de aterrizaje"},
        )

        print("\n6. shipment.incident -> Fleet pone el vehículo fuera de servicio")
        drenar_y_entregar("shipment", "shipment.incident")
        _, vh = http("GET", f"http://localhost:8001/api/v1/vehiculos/{vehicle_id}")
        print(f"   vehículo: {ANSI_ROJO}{vh['status']}{ANSI_FIN}")

        print("\n7. vehicle.status_changed -> Routing recalcula sin alternativas")
        drenar_y_entregar("fleet", "vehicle.status_changed")

        print("\n8. route.unassignable -> Shipment marca el envío retrasado")
        drenar_y_entregar("routing", "route.unassignable")

        print("\n9. shipment.delayed (Fin de la saga del incidente)")
        drenar_y_entregar("shipment", "shipment.delayed")

        _, seg = http("GET", f"http://localhost:8004/api/v1/envios/{shipment_id}/seguimiento")
        _, ruta = http("GET", f"http://localhost:8003/api/v1/rutas/shipment/{shipment_id}")
        print(f"\n{ANSI_VERDE}RESULTADO{ANSI_FIN}")
        print(f"   envío: estado={seg['estado']}, motivo={seg['motivo']!r}")
        print(f"   ruta : {ruta['id']} -> {ruta['estado']}")
        ok = seg["estado"] == "retrasado"
        print(f"   -> {'SAGA OK' if ok else 'SAGA FALLÓ'}")
        return 0 if ok else 1
    finally:
        detener()


if __name__ == "__main__":
    sys.exit(main())
