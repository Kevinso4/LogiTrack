# CONTRATOS del bus y del REST (LogiTrack ↔ Fleet del compañero)

Documento de verdad sobre la **forma** con la que se comunican los
microservicios entre sí y con el Fleet del compañero. Cada ejemplo está
verificado por `test_contratos.py` en `routing-service` y `shipment-service`,
que capturan lo que el publicador REAL escribe en el outbox (no una
maqueta) y lo comparan con los fixtures JSON de este documento.

---

## 1. Sobre (envelope) del evento

Todo evento viaja sobre RabbitMQ (exchange `topic`, durable) con un sobre
que **nunca cambia** entre dialectos.

### 1.1 Dialecto propio (LogiTrack)

| Campo | Tipo | Regla |
|---|---|---|
| `event_id` | `string (uuid-v4)` | **Se conserva tal cual en cualquier traducción**; da la idempotencia por consumidor |
| `event_type` | `string` | Routing key = tipo (`vehicle.status_changed`, `route.assigned`, …) |
| `occurred_at` | `string ISO-8601` | UTC, p. ej. `2026-09-20T12:00:00+00:00` |
| `producer` | `string` | Nombre del servicio que lo originó (`fleet-service`, `routing-service`, …) |
| `trace_id` | `string \| null` | Cadena de correlación; la inyecta el API Gateway (`X-Trace-Id`) |
| `payload` | `object` | Depende del tipo; ver sección 4 |

```json
{
  "event_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "event_type": "shipment.created",
  "occurred_at": "2026-09-20T12:00:00+00:00",
  "producer": "shipment-service",
  "trace_id": null,
  "payload": {}
}
```

### 1.2 Dialecto del compañero

| Campo | Tipo | Regla |
|---|---|---|
| `event_id` | `string` | El mismo que conservamos |
| `tipo` | `string` | Equivale a nuestro `event_type` |
| `ocurrido_en` | `string ISO-8601` | UTC con `Z`, p. ej. `2026-09-20T12:00:00Z` |
| `origen` | `string` | Equivale a nuestro `producer` |
| `agregado_id` | `string \| null` | Id del agregado del evento (`shipment_id`/`vehicle_id` según el tipo) |
| `datos` | `object` | Equivale a nuestro `payload` |

> **`trace_id` no existe en el dialecto del compañero.** El `interop-bridge`
> lo genera (uuid-v4) cuando no viene, o lo conserva si lo trae en su `datos`,
> y lo propaga en los **headers AMQP** (`trace_id`) del mensaje traducido.

---

## 2. Vocabulario de estados del vehículo

El Fleet del compañero habla otro dialecto para lo mismo. La equivalencia la
mantiene `routing-service/app/interop.py` (y su **espejo** en el bridge):

| Propio (LogiTrack) | Compañero |
|---|---|
| `activo` | `disponible` |
| `en_transito` | `en_ruta` |
| `en_mantenimiento` | `mantenimiento` |
| `fuera_de_servicio` | `fuera_servicio` |

Regla: un estado desconocido **viaja tal cual** (passthrough); jamás se
descarta un vehículo por una etiqueta nueva.

---

## 3. Matriz de eventos

| Evento | Publica | Consume | Estado en este repo |
|---|---|---|---|
| `shipment.created` | shipment-service | routing-service | ✅ implementado |
| `route.assigned` | routing-service | shipment-service | ✅ implementado |
| `route.recalculated` | routing-service | shipment-service | ✅ implementado |
| `route.unassignable` | routing-service | shipment-service | ✅ implementado |
| `vehicle.status_changed` | fleet-service; y el **compañero** (vía bridge) | routing-service | ✅ implementado |
| `telemetry.aggregated` | tracking-service | routing-service | ✅ implementado |
| `telemetry.raw` | tracking-service | *ninguno* (persistencia histórica) | ✅ implementado |
| `shipment.incident` | shipment-service; y el **compañero** (vía bridge, traducido a `datos.vehiculo_id`) | fleet-service | ✅ implementado |
| `shipment.delivered` | shipment-service | *ninguno* en el stack | ✅ implementado |
| `shipment.returned` | shipment-service | *ninguno* en el stack | ✅ implementado |
| `shipment.delayed` | shipment-service | *ninguno* en el stack | ✅ implementado |
| `maintenance.alert` / `maintenance.completed` | **sin productor en este repo** | fleet-service | ⚠️ solo consumidor (docs de la matriz original) |

> Divergencias conocidas con respecto al documento del curso: ver sección 7.

---

## 4. Forma exacta de cada payload

Voltios/campos fijados por los fixtures JSON de `tests/fixtures/` (los
`*_contratos.py` los validan contra el outbox real). Los valores son
ejemplificativos: lo que se verifica es el **conjunto de claves y tipos**.

### 4.1 `vehicle.status_changed`

**Payload propio** (publica fleet-service):

```json
{
  "vehicle_id": "v-9a4c",
  "plate": "ABC-123",
  "estado_anterior": "activo",
  "estado_nuevo": "fuera_de_servicio",
  "asignable": false,
  "motivo": "incidente en ruta",
  "zona": "monteria",
  "origen": "shipment.incident"
}
```

**`datos` del compañero** (publica él en `logitrack.fleet`, que el bridge
traduce):

```json
{
  "vehiculo_id": "v-9a4c",
  "placa": "ABC-123",
  "estado_anterior": "disponible",
  "estado_nuevo": "fuera_servicio",
  "motivo": "incidente en ruta",
  "zona_operacion": "monteria"
}
```

Traducción del bridge: `vehiculo_id→vehicle_id`, `placa→plate`,
`zona_operacion→zona`, estados por la tabla de la sección 2. `asignable`,
`origen` y `zona` (ausentes) viajan como `null` si el consumidor los exige.

### 4.2 `shipment.created` (propio)

```json
{
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "client_id": "cliente-x",
  "origen": { "lat": 8.75, "lon": -75.88, "direccion": "Industrial Las Américas, Montería" },
  "destino": { "lat": 10.96, "lon": -74.77, "direccion": "Zona Franca, Barranquilla" },
  "peso_kg": 8000,
  "volumen_m3": 20,
  "is_international": false,
  "sla_deadline": "2026-09-25T20:00:00+00:00",
  "requiere_refrigeracion": true,
  "requiere_hazmat": false,
  "ventana_entrega": { "desde": "2030-01-15T08:00:00+00:00", "hasta": "2030-01-15T20:00:00+00:00" }
}
```

`sla_deadline` y `ventana_entrega` son `null` cuando no se informan.

### 4.3 `route.assigned` (propio)

```json
{
  "ruta_id": "r-5f0a",
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "vehicle_id": "v-9a4c",
  "vehicle_plate": "ABC-123",
  "eta": "2026-09-24T18:30:00+00:00",
  "distancia_km": 650,
  "duracion_min": 1110,
  "tipo_calculo": "calculado",
  "motivo": "asignacion_inicial"
}
```

### 4.4 `route.recalculated` (propio)

Mismas claves que `route.assigned`. `tipo_calculo` puede ser `"calculado"` o
`"estimado"` (sin proveedor de mapas); `motivo` típico: `"ruta recalculada"`,
`"desvio_telemetria"`, o `"vehicle.status_changed:<estado>"`.

### 4.5 `route.unassignable` (propio)

```json
{
  "ruta_id": "r-5f0a",
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "motivo": "la ventana de entrega no es alcanzable con este vehículo",
  "causa": "ventana_incumplible"
}
```

### 4.6 `shipment.incident`

**Payload propio**:

```json
{
  "vehicle_id": "v-9a4c",
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "tipo": "averia",
  "confirmado": true,
  "motivo": "falla hidráulica"
}
```

**`datos` para el compañero** (traduce el bridge: `vehicle_id→vehiculo_id`,
`shipment_id→envio_id`):

```json
{
  "vehiculo_id": "v-9a4c",
  "envio_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "tipo": "averia",
  "confirmado": true,
  "motivo": "falla hidráulica"
}
```

El compañero lee `datos.vehiculo_id`; CUALQUIER `shipment.incident` (aunque
venga del bridge) pone su vehículo en `fuera_servicio` — no tocamos su código.

### 4.7 `shipment.delivered` (propio)

```json
{
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "entregado_en": "2026-09-24T18:40:00+00:00",
  "vehicle_id": "v-9a4c",
  "vehicle_plate": "ABC-123",
  "destinatario": "Ana García"
}
```

### 4.8 `shipment.returned` y `shipment.delayed` (propio)

```json
{ "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001", "motivo": "devolución al origen" }

{
  "shipment_id": "f9cf8f4c-108d-4ac8-9fce-deadbeef0001",
  "motivo": "sin vehículo viable",
  "nueva_eta": null
}
```

### 4.9 `telemetry.aggregated` (propio)

```json
{
  "vehicle_id": "v-9a4c",
  "ventana_inicio": "2026-09-21T10:00:00+00:00",
  "ventana_fin": "2026-09-21T11:00:00+00:00",
  "lecturas": 360,
  "velocidad_promedio_kmh": 52.3,
  "velocidad_maxima_kmh": 88,
  "temperatura_motor_max_c": 94.2,
  "combustible_pct": 60,
  "odometro_km": 124500,
  "distancia_km": 25.7,
  "horas_motor": 4.2,
  "codigos_obd2": [],
  "ultima_posicion": { "lat": 9.3, "lon": -75.4 },
  "detenido": false
}
```

### 4.10 `maintenance.alert` / `maintenance.completed`

Fleet los **consume** (ponen el vehículo en `en_mantenimiento` /
`activo`), pero **ningún servicio de este repo los publica**. Para probar la
cascada se publican a mano en la consola de RabbitMQ o con
`POST /internal/bus/deliver` (solo `DEMO_BUS_INTERNO=true`). Forma esperada:
sobre propio con `payload.vehicle_id` (o `payload.vehiculo_id`).

---

## 5. Contrato REST `GET /api/v1/vehiculos/disponibles`

### 5.1 Propio (fleet-service `:8001`)

Filtros por query string: `capacidad_min_kg`, `volumen_min_m3`,
`refrigerado` (`"true"`), `hazmat` (`"true"`), `zona`, `tipo`. Respuesta:

```json
[
  {
    "id": "v-9a4c",
    "plate": "ABC-123",
    "type": "refrigerado",
    "capacity_kg": 12000,
    "capacity_m3": 45,
    "zona": "monteria",
    "refrigeration_capable": true,
    "hazmat_certified": false
  }
]
```

### 5.2 Compañero

El compañero **no entiende `volumen_min_m3`** y responde con otro vocabulario.
`ClienteFleetCompanero` (seam 1, activado con `FLEET_DIALECTO=companero` en
routing-service) consulta su URL sin ese filtro y **filtra la capacidad en
memoria**:

- Filtros que sí acepta: `capacidad_min_kg`, `refrigerado`, `hazmat`.
- Respuesta plana (un objeto por vehículo, sin anidar):

```json
[
  {
    "id": "v-9a4c",
    "placa": "ABC-123",
    "tipo": "refrigerado",
    "capacidad_kg": 12000,
    "capacidad_m3": 45,
    "anio": 2023,
    "vencimiento_seguro": "2026-12-31",
    "estado": "disponible",
    "refrigerado": true,
    "certificado_hazmat": false,
    "zona_operacion": "monteria"
  }
]
```

Traducción a `VehiculoDisponible`: `placa→plate`, `tipo→type`,
`capacidad_kg→capacity_kg`, `capacidad_m3→capacity_m3`,
`zona_operacion→zona`, `refrigerado→refrigeration_capable`,
`certificado_hazmat→hazmat_certified`. Solo pasan a Routing los vehículos
cuyo estado equivale a `activo` y con `capacidad_m3 >= volumen_min_m3`.

---

## 6. El Interop Bridge (seam 2)

Servicio `interop-bridge/` (puerto `:8005`, perfil Docker `interop`, sin DB):

| Dirección | Exchange de entrada (cola) | Routing key | Exchange de salida | Routing key |
|---|---|---|---|---|
| Entrante | `logitrack.fleet` (`interop.fleet`) | `vehicle.status_changed` | `logitrack.events` | `vehicle.status_changed` |
| Saliente | `logitrack.events` (`interop.shipment`) | `shipment.incident` | `logitrack.shipment` | `shipment.incident` |

- Colas `durable` con DLQ (`<exchange>.dlx` / `interop.*.dlq`).
- `event_id` intacto; `trace_id` generado o conservado y propagado por header.
- Un sobre ilegible o no publicable va a la DLQ, jamás bloquea la cola.
- Los logs son JSON y la traducción vive en funciones puras (`app/traductor`).

Levantar:

```bash
docker compose up -d --build --profile interop
```

Para que Routing asigne contra el Fleet del compañero (en lugar del propio):

```bash
# routing-service/.env
FLEET_DIALECTO=companero
FLEET_URL=http://host-del-companero:8001   # su /api/v1/vehiculos/disponibles
```

---

## 7. Divergencias conocidas entre el PROMPT y el código real

| El PROMPT decía | La realidad del repo |
|---|---|
| `shipment.assigned` | No existe: Shipment se entera de la asignación vía `route.assigned` / `route.recalculated` |
| `route.calculated` | No existe: Routing publica `route.assigned` / `route.recalculated` |
| `maintenance.alert`/`maintenance.completed` con productor en el repo | Solo hay consumidor (fleet-service); los productores (maintenance-service) no están en esta entrega |
| Total de tests del prompt: 125 | Verde real: **164** (fleet 25 + tracking 27 + routing 56 + shipment 44) + 12 del bridge = 164 |