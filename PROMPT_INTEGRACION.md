# Tarea: cerrar LogiTrack e integrar con el Fleet del compañero

Trabajas en `C:\Users\keyne\Documents\LogiTrack`. Es un proyecto universitario de
microservicios (FastAPI + PostgreSQL + RabbitMQ + Docker). Ya está construido y
funcionando; tu trabajo es cerrarlo, no rehacerlo. **No reescribas dominio que ya
pasa tests.**

## Estado actual del repo

Cuatro servicios, todos operativos y verificados en Docker de punta a punta:

| Servicio | Puerto | Base | Dueño |
|---|---|---|---|
| fleet-service | 8001 | fleet_db | dependencia de desarrollo |
| tracking-service | 8002 | tracking_db (TimescaleDB) | dependencia de desarrollo |
| **routing-service** | 8003 | routing_db | **entregable** |
| **shipment-service** | 8004 | shipment_db | **entregable** |

125 tests pasando (25 + 27 + 42 + 38), sin Docker, contra SQLite y bus en memoria.
CI en `.github/workflows/ci.yml` ya existe.

Patrones implementados: Outbox con relay en segundo plano (`FOR UPDATE SKIP LOCKED`),
consumidores idempotentes por `event_id`, saga coreografiada sin orquestador, DLQ por
cola, trazas `X-Trace-Id`, logs JSON, métricas Prometheus, inversión de dependencias
en los puertos de salida (`PublicadorEventos`, `ProveedorMapas`, `ClienteFleet`).

### Contrato de eventos propio (el que usan los 4 servicios de este repo)

Un único exchange topic `logitrack.events`. Routing key = `event_type`.

```json
{
  "event_id": "uuid",
  "event_type": "shipment.incident",
  "occurred_at": "2026-09-21T01:00:00Z",
  "producer": "shipment-service",
  "trace_id": "uuid",
  "payload": { }
}
```

---

## PARTE 0 — Commit de seguridad (hazlo PRIMERO, antes de tocar nada)

Hay 16 archivos modificados y 5 sin trackear que son arreglos ya verificados en
producción local. Están sin commitear y eso es el único riesgo real ahora mismo.

Son seis correcciones de resiliencia del bus encontradas corriendo el sistema de
verdad (los 125 tests seguían en verde mientras el sistema estaba sordo al bus):

1. `app/events/conector.py` (nuevo en los 4 servicios) — los consumidores se
   rendían ante `[Errno 111] Connection refused` y nunca reintentaban. Ahora hay
   backoff exponencial 1s → 30s.
2. Healthcheck de RabbitMQ: `rabbitmq-diagnostics ping` reportaba sano ~20 s antes
   de que el puerto 5672 aceptara conexiones. Cambiado a `check_port_connectivity`,
   `start_period: 60s`.
3. Publicación con `mandatory=True` + `on_return_raises` y excepción
   `EventoNoRuteable`: un evento publicado a un exchange sin cola bindeada se
   descartaba en silencio. **Importante: `mandatory` está aplicado solo a los
   eventos que tienen consumidores — NO a `telemetry.raw`**, que no tiene ninguno
   por diseño y generaría falsos positivos masivos en el servicio de mayor caudal.
4. Máquina de estados de envío: `retrasado → incidente` estaba permitido y un
   segundo POST hacía retroceder el envío. Prohibido. `retrasado → en_ruta` se
   permite pero solo por evento, nunca desde la API.
5. `entrypoint.sh` de los 4 servicios: crash-loop enmascarado por
   `restart: unless-stopped` (84 tracebacks idénticos de `socket.gaierror` en
   alembic). Ahora espera la base (30×2s) y reintenta migraciones (5×3s).
6. CORS habilitado en los 4 `app/main.py` para el panel de demostración
   (`panel.html` en la raíz).

**Haz esto:**

```
git add -A
git commit
```

Mensaje sugerido (multilínea, en español, describiendo los 6 puntos de arriba de
forma concisa). **Revisa antes que `.venv/`, `__pycache__/` y `tracking.log` estén
ignorados** — `tracking.log` no está en `.gitignore` y no debe entrar al repo.

Después del commit, corre `pytest -q` en los cuatro servicios y confirma que siguen
los 125 en verde. Si alguno falla, arréglalo antes de seguir.

---

## PARTE 1 — Integración con el Fleet del compañero (lo importante)

En la entrega final el Fleet que se usa **no es el de este repo**, es el de un
compañero de equipo. Su implementación es independiente y el contrato **no coincide**.
El Fleet local de este repo se queda como dependencia de desarrollo y para los tests.

### Diferencias reales entre los dos Fleet (ya analizadas, no las investigues)

**a) Sobre del evento — incompatible**

| Campo propio | Campo del compañero |
|---|---|
| `event_type` | `tipo` |
| `occurred_at` | `ocurrido_en` |
| `producer` | `origen` |
| `payload` | `datos` |
| `trace_id` | *(no existe)* |
| *(no existe)* | `agregado_id` |

**b) Topología del bus — incompatible**

- Propia: un solo exchange topic `logitrack.events`, routing key = `event_type`.
- Compañero: un exchange **por servicio productor** — `logitrack.fleet`,
  `logitrack.maintenance`, `logitrack.shipment` — routing key = `tipo`.
  Su cola de consumo es `fleet.inbox`, con DLQ por `x-dead-letter-exchange`.

**c) Vocabulario de estados del vehículo — incompatible**

| Propio | Compañero |
|---|---|
| `activo` | `disponible` |
| `en_transito` | `en_ruta` |
| `en_mantenimiento` | `mantenimiento` |
| `fuera_de_servicio` | `fuera_servicio` |

**d) `GET /api/v1/vehiculos/disponibles` — parcialmente incompatible**

- Filtros que acepta el compañero: `tipo`, `zona`, `capacidad_min_kg`,
  `refrigerado`, `hazmat`. **No acepta `volumen_min_m3`**, que sí manda el
  `ClienteFleetREST` actual de Routing.
- Respuesta: lista plana (no paginada) de
  `{id, placa, tipo, capacidad_kg, capacidad_m3, anio, vencimiento_seguro, estado, refrigerado, certificado_hazmat, zona_operacion}`.
- Nombres distintos: `capacidad_m3` (propio: `volumen_m3`), `zona_operacion`
  (propio: `zona`), `certificado_hazmat` (propio: `hazmat`).

**e) Payloads que su Fleet produce y consume**

- Publica `vehicle.status_changed` con
  `datos = {vehiculo_id, placa, estado_anterior, estado_nuevo, motivo, zona_operacion}`.
  Nota: `vehiculo_id` (español), el propio usa `vehicle_id`. No trae `asignable`.
- Consume `maintenance.alert`, `maintenance.completed` y `shipment.incident`,
  leyendo siempre `datos.vehiculo_id`.
- **Su regla de negocio difiere:** cualquier `shipment.incident` lo manda a
  `fuera_servicio`. El propio solo lo hace con tipo avería/accidente **y**
  `confirmado: true`. No intentes cambiar su código.

### Cómo integrarlo: capa anticorrupción, NO reescritura

Regla dura: **el dominio de Routing y Shipment no se toca.** El contrato ajeno se
traduce en el borde. Esto es una capa anticorrupción (ACL) de DDD y es exactamente
lo que hay que poder defender en la sustentación. Además mantiene los 125 tests
intactos y deja el Fleet propio funcionando en paralelo.

**Seam 1 — REST (fácil, el punto de extensión ya existe).**

`routing-service/app/cliente_fleet.py` ya define la interfaz abstracta
`ClienteFleet` con implementaciones `ClienteFleetREST` y `ClienteFleetFake`.
Agrega una tercera: `ClienteFleetCompanero(ClienteFleet)`, que:

- no manda `volumen_min_m3` en la query (filtra por `capacidad_m3` en memoria
  después de recibir la respuesta);
- mapea `capacidad_m3 → volumen_m3`, `zona_operacion → zona`,
  `certificado_hazmat → hazmat`;
- traduce el estado al vocabulario propio con una tabla de equivalencias en un
  único módulo nuevo `routing-service/app/interop.py` (esa tabla se reutiliza en
  el seam 2, no la dupliques).

Selecciónala por variable de entorno: `FLEET_DIALECTO=propio|companero`, default
`propio`. La fábrica que hoy construye el cliente decide según ese valor. Un solo
`if`, en un solo sitio.

**Seam 2 — Bus (un puente, no parches en los servicios).**

Crea un servicio nuevo y pequeño en `interop-bridge/` (≈150 líneas, un solo
`app/main.py` + `Dockerfile`, sin base de datos). Es un traductor bidireccional:

- **Entrante:** se suscribe a `logitrack.fleet` (formato compañero, routing key
  `vehicle.status_changed`), traduce el sobre y el vocabulario de estados al
  formato propio, y republica en `logitrack.events`. Así Routing y Shipment
  consumen lo que siempre consumieron, sin enterarse.
- **Saliente:** se suscribe a `logitrack.events` con routing key
  `shipment.incident`, traduce al sobre del compañero
  (`vehicle_id → vehiculo_id`, `shipment_id → envio_id`) y publica en
  `logitrack.shipment`, que es donde su Fleet escucha.

Requisitos del puente:
- Idempotente: conserva el `event_id` original al traducir, para que el consumidor
  destino pueda deduplicar. No generes uno nuevo.
- Propaga `trace_id` cuando exista; cuando venga del compañero (que no lo tiene),
  genera uno y déjalo registrado en el log para poder seguir la traza igual.
- Reusa el `conector.py` con backoff que ya existe en los otros servicios en vez de
  escribir otro loop de reconexión.
- Logs JSON con el mismo formato que los demás servicios.
- Declara el exchange y las colas como `durable=True`, con DLQ, igual que el resto.
- Tests propios: al menos 6, sobre la función pura de traducción en ambos sentidos
  (sobre, vocabulario de estados, nombres de campos, conservación de `event_id`).
  Sin RabbitMQ, igual que los demás.

Añádelo a `docker-compose.yml` bajo un **profile** llamado `interop`, para que
`docker compose up` normal no lo levante y el stack de desarrollo siga idéntico.
Documenta en el README cómo levantarlo:
`docker compose --profile interop up -d`.

---

## PARTE 2 — Documentación del contrato

Crea `CONTRATOS.md` en la raíz. Es el documento que el equipo usa como fuente de
verdad y el que sustenta la defensa. Debe contener:

1. El sobre canónico del evento, campo por campo, con tipos.
2. Tabla de la matriz de eventos: quién publica qué, quién lo consume, y con qué
   efecto de negocio.
3. El payload exacto, campo por campo con tipo y obligatoriedad, de:
   `vehicle.status_changed`, `shipment.created`, `shipment.assigned`,
   `shipment.incident`, `shipment.delivered`, `route.calculated`,
   `telemetry.aggregated`, `maintenance.alert`.
   (Sácalos del código real de este repo, no los inventes.)
4. El contrato REST de `GET /api/v1/vehiculos/disponibles`: query params, forma de
   la respuesta, códigos de error.
5. Una sección **"Divergencias conocidas con la implementación del compañero"**
   con las tablas a/b/c/d de la Parte 1 y la explicación de cómo el puente las
   resuelve.

Después, agrega **tests de contrato** en `routing-service/tests/test_contratos.py`
y `shipment-service/tests/test_contratos.py`: fixtures JSON con un evento de
ejemplo de cada tipo, y una prueba que valide que el publicador real produce
exactamente esa forma. Si mañana alguien renombra un campo, el test cae. Eso es el
punto.

---

## PARTE 3 — Cierre

1. **Verifica Tracking de verdad.** Nunca recibió telemetría real corriendo en
   Docker; es el único hueco de verificación que queda. Levanta el stack y corre:
   ```
   C:\Users\keyne\Documents\LogiTrack\.venv\Scripts\python.exe tracking-service\scripts\simulador_iot.py --fleet-url http://localhost:8001 --vehiculos 1 --intervalo 2 --iteraciones 5
   ```
   Confirma que las lecturas entran (`GET /api/v1/telemetria/{id}/ultima`), fuerza
   una agregación con `POST /api/v1/telemetria/agregacion/ejecutar` y comprueba en
   los logs de Routing que llegó el `telemetry.aggregated`. Si algo falla, arréglalo
   y dilo.

2. **`panel.html`** (raíz del repo, panel de demostración sin dependencias) usa los
   nombres de estado propios para los badges de color. Agrégale el vocabulario del
   compañero (`disponible`, `en_ruta`, `mantenimiento`, `fuera_servicio`) para que
   sirva contra cualquiera de los dos Fleet.

3. **README:** agrega una sección corta explicando por qué el repo trae su propio
   Fleet y Tracking —son dependencias de desarrollo que permiten correr y testear
   Routing y Shipment de forma aislada— y que en la integración final el Fleet que
   manda es el del compañero, conectado vía `interop-bridge` y
   `FLEET_DIALECTO=companero`.

4. Commit final. Deja el árbol limpio.

---

## Reglas de trabajo

- Español en código, comentarios, mensajes de commit y documentación.
- `black --line-length 100` y `flake8` limpios antes de cada commit.
- No toques la lógica de dominio que ya pasa tests. Si crees que hay que hacerlo,
  **pregunta antes** explicando por qué.
- No agregues dependencias nuevas sin justificarlo.
- Si algo del plan no te cuadra o encuentras una incoherencia en lo que te acabo de
  describir, dilo antes de empezar en vez de improvisar.
- Trabaja en el orden: Parte 0 → Parte 1 → Parte 2 → Parte 3. La Parte 0 es
  bloqueante.
