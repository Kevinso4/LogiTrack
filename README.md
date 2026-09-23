# LogiTrack — Fleet, Tracking, Routing y Shipment

Implementación de los cuatro primeros microservicios del ecosistema LogiTrack
(Momento 1 · Ingeniería de Sistemas, UCC Montería), siguiendo el documento de
arquitectura: FastAPI sobre Python, *Database per Service*, comunicación
híbrida REST + eventos, patrón Outbox, consumidores idempotentes, Docker
multi-stage y CI con GitHub Actions.

| Servicio | Puerto | Base de datos | Publica | Consume |
|---|---|---|---|---|
| **fleet-service** | 8001 | `fleet_db` (PostgreSQL 16) | `vehicle.status_changed` | `maintenance.alert`, `shipment.incident` |
| **tracking-service** | 8002 | `tracking_db` (PostgreSQL + TimescaleDB) | `telemetry.raw`, `telemetry.aggregated` | *ninguno* |
| **routing-service** | 8003 | `routing_db` (PostgreSQL 16) | `route.assigned`, `route.recalculated`, `route.unassignable` | `shipment.created`, `telemetry.aggregated`, `vehicle.status_changed` |
| **shipment-service** | 8004 | `shipment_db` (PostgreSQL 16) | `shipment.created`, `shipment.delivered`, `shipment.incident`, `shipment.returned`, `shipment.delayed` | `route.assigned`, `route.recalculated`, `route.unassignable`, `customs.held`, `customs.cleared` |
| **interop-bridge** (perfil `interop`) | 8005 | *ninguna* | `vehicle.status_changed`, `shipment.incident` (traducidos) | `shipment.incident` (propio), `vehicle.status_changed` (compañero) |

> `customs.held` y `customs.cleared` son un **desvío deliberado** de la matriz:
> el Shipment Service escucha además de los eventos de ruta la retención en
> aduana, porque solo él conoce el estado real del envío. El resto del stack no
> publica ni consume esos eventos.

---

## 1. Levantar todo (Docker)

```bash
docker compose up --build
```

Eso arranca PostgreSQL/TimescaleDB, RabbitMQ, Redis (caché de ETA opcional) y
los cuatro servicios. Las migraciones de Alembic corren solas al iniciar cada
contenedor.

El **interop-bridge** (capa anticorrupción con el Fleet del compañero) arranca
solo con su perfil, para que el stack base no dependa de la disponibilidad de
ese Fleet:

```bash
docker compose --profile interop up -d --build
```

| Qué | Dónde |
|---|---|
| Swagger de Fleet | http://localhost:8001/docs |
| Swagger de Tracking | http://localhost:8002/docs |
| Swagger de Routing | http://localhost:8003/docs |
| Swagger de Shipment | http://localhost:8004/docs |
| Health del Interop Bridge | http://localhost:8005/health/live |
| Consola de RabbitMQ | http://localhost:15672 (`logitrack` / `logitrack`) |
| Métricas Prometheus | `:8001/metrics` … `:8004/metrics` |

### Datos de prueba y simulador IoT

```bash
# Carga 5 vehículos y 3 conductores
cd fleet-service && python scripts/seed.py

# Dispositivos embarcados mandando telemetría cada 10 s (Ctrl+C para parar)
cd tracking-service
python scripts/simulador_iot.py --fleet-url http://localhost:8001 --vehiculos 5
python scripts/simulador_iot.py --fabricante queclink --intervalo 2 --con-errores
```

El simulador puede emitir en el formato de tres fabricantes distintos
(`generico`, `queclink` en mph/°F/millas, `teltonika` con campos abreviados y
odómetro en metros) para ver la normalización en acción.

## 2. Levantar sin Docker

Necesitas PostgreSQL y RabbitMQ accesibles. En cada servicio:

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements-dev.txt
copy .env.example .env                              # y ajusta las URLs
alembic upgrade head
uvicorn app.main:app --reload --port 8001           # 8002 en tracking
```

Si no hay broker, arranca con `BUS_HABILITADO=false`: la API funciona igual y
los eventos se quedan en el outbox.

## 3. Tests

```bash
cd fleet-service    && pytest -q     # 25 tests
cd tracking-service && pytest -q     # 27 tests
cd routing-service  && pytest -q     # 56 tests
cd shipment-service && pytest -q     # 44 tests
cd interop-bridge   && pytest -q     # 12 tests   # total: 164
```

Corren contra SQLite y con el bus en memoria: **no necesitan Docker**, que es
lo que permite que el CI de GitHub Actions sea rápido. El código de producción
no cambia — solo se sustituye la URL de la base y la implementación de
`PublicadorEventos` (principio de sustitución de Liskov en la práctica).

Calidad igual que en el pipeline:

```bash
black --check --line-length 100 app tests scripts
flake8 app tests scripts
```

---

## 4. Endpoints

### Fleet Service (`:8001`)

| Método | Ruta | Para qué |
|---|---|---|
| `GET` | `/api/v1/vehiculos/disponibles` | **La consulta que hace Routing** antes de asignar carga. Filtros: `tipo`, `zona`, `capacidad_min_kg`, `volumen_min_m3`, `refrigerado`, `hazmat` |
| `GET` | `/api/v1/vehiculos` | Catálogo paginado (`estado`, `zona`, `limite`, `desplazamiento`) |
| `POST` | `/api/v1/vehiculos` | Alta de vehículo |
| `GET` | `/api/v1/vehiculos/{id}` | Ficha técnica |
| `PATCH` | `/api/v1/vehiculos/{id}` | Actualizar ficha |
| `PATCH` | `/api/v1/vehiculos/{id}/estado` | Cambiar estado operativo (valida la máquina de estados y publica evento) |
| `POST` | `/api/v1/conductores` | Alta de conductor |
| `GET` | `/api/v1/conductores/{id}/disponibilidad` | Licencia vigente + tope semanal de conducción |
| `PUT` | `/api/v1/conductores/{id}/vehiculo` | Asignar vehículo |
| `POST` | `/api/v1/conductores/{id}/horas` | Registrar horas conducidas |

Estados y transiciones legales:

```
activo ──────────► en_transito ──────► activo
   │                    │
   ├──► en_mantenimiento ◄── fuera_de_servicio
   └──► fuera_de_servicio ◄──┘
```

Un vehículo `fuera_de_servicio` **no** vuelve a `activo` directamente: tiene
que pasar por taller (`en_mantenimiento`). Intentarlo devuelve `422`.

### Tracking Ingestion Service (`:8002`)

| Método | Ruta | Para qué |
|---|---|---|
| `POST` | `/api/v1/telemetria` | Ingesta en lote (202 Accepted). Cabecera `X-API-Key` si hay claves configuradas |
| `GET` | `/api/v1/telemetria/{id}/ultima` | Última posición conocida |
| `GET` | `/api/v1/telemetria/{id}/recorrido?desde&hasta` | Recorrido + distancia (haversine) + velocidades |
| `POST` | `/api/v1/telemetria/agregacion/ejecutar` | Fuerza el cierre de la ventana de agregación (demo/operación) |

Ejemplo de ingesta con un dispositivo que manda en unidades imperiales (el
compose define `demo-logitrack` como API key; en local sin claves la cabecera
se omite):

```bash
curl -X POST localhost:8002/api/v1/telemetria -H "Content-Type: application/json" -H "X-API-Key: demo-logitrack" -d '{
  "device_id": "iot-77",
  "fabricante": "queclink",
  "lecturas": [{
    "vehicle_id": "<id-del-vehiculo>",
    "time": "2026-09-20T13:00:00Z",
    "latitude": 8.75, "longitude": -75.88,
    "speed": 60, "engine_temp": 194, "odometer": 100
  }]
}'
```

Respuesta: `speed_kmh = 96.56`, `engine_temp_c = 90.0`, `odometer_km = 160.93`.

### Routing Service (`:8003`)

| Método | Ruta | Para qué |
|---|---|---|
| `POST` | `/api/v1/rutas/{ruta_id}/recalcular` | Forzar recálculo (operación / advertencia) |
| `GET` | `/api/v1/rutas/{ruta_id}` | Consulta una ruta |
| `GET` | `/api/v1/rutas/shipment/{shipment_id}` | Ruta asociada a un envío |
| `GET` | `/api/v1/drivers/navegacion/{shipment_id}` | Tipo delgado para el conductor (`shiptop`: próximas paradas) |

La hoja de ruta (asignación) se dispara sola al llegar `shipment.created`;
`telemetry.aggregated` mantiene la ruta al día y `vehicle.status_changed` la
recalcula si el vehículo queda fuera. El REST a Fleet
(`GET /api/v1/vehiculos/disponibles`) es el único camino síncrono del stack.

### Shipment Service (`:8004`)

| Método | Ruta | Para qué |
|---|---|---|
| `POST` | `/api/v1/envios` | Alta de envío → publica `shipment.created` |
| `GET` | `/api/v1/envios?estado` | Envíos del equipo de operaciones |
| `GET` | `/api/v1/envios/{id}` | Ficha completa |
| `GET` | `/api/v1/envios/{id}/seguimiento` | Tipo delgado para el cliente (sin internals) |
| `GET` | `/api/v1/envios/{id}/historial` | Auditoría de transiciones |
| `POST` | `/api/v1/envios/{id}/incidente` | Reporta incidente → `shipment.incident` si es confirmado |
| `POST` | `/api/v1/envios/{id}/entregar` | Entrega con POD → `shipment.delivered` |
| `POST` | `/api/v1/envios/{id}/devolver` | Devolución → `shipment.returned` |

#### Contrato de `shipment.created`

La única fuente de la saga. Lo publica Shipment al crear el envío y lo consumen
Routing (y cualquiera que se suscriba dentro del stack):

```json
{
  "event_type": "shipment.created",
  "event_id": "uuid-v4",
  "producer": "shipment-service",
  "occurred_at": "2026-09-20T12:00:00+00:00",
  "payload": {
    "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
    "client_id": "cliente-x",
    "origen": {"lat": 8.75, "lon": -75.88, "direccion": "Industrial Las Américas, Montería"},
    "destino": {"lat": 10.96, "lon": -74.77, "direccion": "Zona Franca, Barranquilla"},
    "peso_kg": 8000,
    "volumen_m3": 20,
    "is_international": false,
    "sla_deadline": "2026-09-25T20:00:00+00:00",
    "requiere_refrigeracion": true,
    "requiere_hazmat": false,
    "ventana_entrega": {"desde": "2026-09-24T08:00:00+00:00", "hasta": "2026-09-24T20:00:00+00:00"}
  }
}
```

`ventana_entrega` es una restricción **dura** para Routing: si ninguna ruta
cabe, se publica `route.unassignable`.

---

## 5. Flujo de eventos implementado

```
 dispositivos IoT
       │ HTTP/2 (lote cada 10 s)
       ▼
 ┌─────────────────┐   telemetry.raw        ┌──────────────┐
 │   TRACKING      │───────────────────────►│              │
 │   INGESTION     │   telemetry.aggregated │   RabbitMQ   │
 └────────┬────────┘───────────────────────►│  (topic +    │
          │ INSERT                          │   DLQ)       │
          ▼                                 └──────┬───────┘
   tracking_db (hypertable, chunks 7 días)         │
                                                   │ maintenance.alert
                                                   │ shipment.incident
                                                   ▼
                                            ┌──────────────┐
  Routing ──REST: /vehiculos/disponibles───►│    FLEET     │
                                            │              │
                                            └──────┬───────┘
                                                   │ vehicle.status_changed
                                                   ▼
                                                RabbitMQ
```

Probado de punta a punta: al publicar un `maintenance.alert` con severidad
crítica, Fleet cambia el vehículo a `en_mantenimiento`, emite
`vehicle.status_changed` y ese vehículo desaparece de `/disponibles`.

Y con el stack real en Docker (desde el contenedor): el `simulador_iot.py`
manda lotes a Tracking, la ventana de agregación escribe `telemetry.aggregated`
en el outbox y el relay lo entrega a Routing, que lo registra en su
`processed_events`. El `interop-bridge` (perfil `interop`) declara sus colas y
DLQ y conecta con RabbitMQ; su `/health/ready` reporta `bus: sano`.

### La saga del incidente (Routing + Shipment + Fleet)

```
                        POST /api/v1/envios/{id}/incidente  (confirmado)
                                     │
                                     ▼
                        shipment-service → pub shipment.incident
                                     │ {vehicle_id, shipment_id, tipo, confirmado}
                                     ▼
                        fleet-service: vehículo → fuera_de_servicio
                                     │ pub vehicle.status_changed
                                     ▼
                        routing-service: recalcula con excluir_vehicle_id
                        ├─ hay vehículo  → pub route.recalculated → Shipment actualiza ETA
                        └─ sin vehículo  → pub route.unassignable → Shipment: retrasado
                                                                    └ pub shipment.delayed
```

Encadenada de punta a punta; en el repo de la raíz está `demo/saga_demo.py`
que la reproduce con cuatro procesos uvicorn locales y SQLite (sin Docker ni
broker, solo disparando los endpooints y el relay del outbox).

## 6. Decisiones de diseño (y por qué)

**Patrón Outbox.** El cambio de estado y la fila del evento se escriben en la
misma transacción; un relay en segundo plano es lo único que habla con
RabbitMQ. Si el broker está caído el evento espera en la tabla y sale cuando
vuelve; si el commit falla, no hay evento fantasma. En PostgreSQL el relay usa
`FOR UPDATE SKIP LOCKED`, así que varias réplicas del servicio pueden correrlo
a la vez sin pisarse.

**`telemetry.raw` se publica directo, sin outbox.** Es el único evento que no
tiene consumidores (matriz de eventos del documento: es persistencia
histórica). Pasarlo por el outbox duplicaría la escritura del servicio de mayor
caudal del sistema a cambio de nada. `telemetry.aggregated`, que sí consumen
Routing y Maintenance, va con garantía transaccional.

**Idempotencia en los dos lados.** El consumidor de Fleet registra cada
`event_id` procesado en la misma transacción que el efecto, así una reentrega
de RabbitMQ no cambia dos veces el estado. En Tracking la clave primaria
`(vehicle_id, time)` más `ON CONFLICT DO NOTHING` hace que reenviar un lote
completo no duplique ni una fila — el `RETURNING` cuenta cuántas entraron de
verdad y la respuesta lo reporta como `duplicadas`.

**Normalización antes de persistir.** Cada fabricante nombra y mide distinto.
`app/normalizacion.py` tiene un perfil por fabricante (alias de campos +
unidades) y convierte todo a km/h, °C, km y %. Una lectura corrupta se rechaza
con un motivo tipificado (`coordenada_invalida`, `velocidad_fuera_de_rango`,
`timestamp_futuro`…) que alimenta la métrica de tasa de error de parseo, y
**el resto del lote se procesa igual**.

**Inversión de dependencias.** La lógica depende de la interfaz
`PublicadorEventos`, no de `aio_pika`. Migrar a Kafka (la alternativa que
contempla el documento si el volumen de telemetría crece) es escribir una
implementación nueva sin tocar la ingesta.

**Cola de mensajes fallidos.** Cada cola de consumo se declara con
`x-dead-letter-exchange`. Un mensaje que revienta no se reintenta en bucle
bloqueando la cola: se va a `fleet.inbox.dlq` para inspección.

**Observabilidad.** Logs JSON con `trace_id` propagado por la cabecera
`X-Trace-Id` (la pone el API Gateway) y métricas Prometheus en `/metrics`,
incluidas las que pide el documento para este servicio: lecturas recibidas y
aceptadas por fabricante, y rechazos etiquetados por motivo.

## 7. Qué NO cubre esta entrega

- Suscriptor MQTT: la ingesta es HTTP en lote. El punto de extensión está en
  `app/servicios.py::procesar_lote`, que no sabe por dónde llegó el dato.
- Pruebas de carga con k6/Artillery (sección 7 del documento).
- Los seis microservicios restantes (customs, maintenance, tracking-ingestion
  como servicio aparte…). Los eventos que consume cada servicio del stack se
  pueden simular publicándolos a mano en el exchange desde la consola de
  RabbitMQ o con el endpoint de demo `POST /internal/bus/deliver` (solo
  `DEMO_BUS_INTERNO=true` y fuera de producción/Docker).
- Autenticación JWT: es responsabilidad del API Gateway. Aquí solo está la
  API key de dispositivos IoT en la ingesta.

## 8. Estructura

```
logitrack/
├── docker-compose.yml          # TimescaleDB + RabbitMQ + Redis + los cuatro servicios
├── infra/init-db.sql           # crea fleet_db, tracking_db, routing_db y shipment_db
├── .github/workflows/ci.yml    # pipeline por servicio afectado
├── demo/saga_demo.py           # saga del incidente en 4 procesos locales (sin Docker)
├── fleet-service/
│   ├── app/
│   │   ├── dominio.py          # estados y transiciones legales del vehículo
│   │   ├── servicios.py        # lógica de negocio
│   │   ├── events/             # outbox, publicador, consumidor, manejadores
│   │   └── routers/
│   ├── alembic/versions/       # esquema de fleet_db
│   ├── scripts/seed.py
│   └── tests/
├── tracking-service/
│   ├── app/
│   │   ├── normalizacion.py    # perfiles de fabricante y conversiones
│   │   ├── servicios.py        # ingesta y consultas
│   │   ├── agregador.py        # ventanas y telemetry.aggregated
│   │   └── routers/
│   ├── alembic/versions/       # hypertable de TimescaleDB
│   ├── scripts/simulador_iot.py
│   └── tests/
├── routing-service/
│   ├── app/
│   │   ├── reglas_ruta.py      # capacidad, horas de conducción, ventanas
│   │   ├── cliente_fleet.py    # REST con timeout, reintentos y circuito
│   │   ├── proveedores_mapa.py # simulado / Mapbox (haversine como fallback)
│   │   ├── cache_redis.py      # caché de ETA opcional (Redis caído ≠ caído)
│   │   ├── servicios.py        # asignar / recalcular / telemetría
│   │   ├── events/             # consumidor de shipment.created, etc.
│   │   └── routers/
│   ├── alembic/versions/       # esquema de routing_db
│   ├── scripts/datos_prueba.py
│   └── tests/
├── shipment-service/
│   ├── app/
│   │   ├── dominio.py          # máquina de estados del envío
│   │   ├── servicios.py        # ciclo de vida completo
│   │   ├── events/             # consumidor de ruta y aduana
│   │   └── routers/
│   ├── alembic/versions/       # esquema de shipment_db
│   ├── scripts/datos_prueba.py
│   └── tests/
└── interop-bridge/             # capa anticorrupción (perfil Docker "interop")
    ├── app/
    │   ├── traductor.py        # traducción pura de sobres y payloads
    │   ├── interop.py          # espejo de la tabla de equivalencias (routing)
    │   ├── bus.py              # exchanges/colas + DLQ, traduce en vivo
    │   └── ...
    └── tests/
```
