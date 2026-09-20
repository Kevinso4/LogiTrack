# Routing Service

Decide qué vehículo lleva cada carga y con qué ruta, en el menor tiempo
posible. Es el tercer servicio del stack LogiTrack (puerto `8003`, base
`routing_db`).

## Responsabilidades

- **Primera asignación**: al recibir `shipment.created`, consulta a Fleet
  (`GET /api/v1/vehiculos/disponibles`) y publica `route.assigned`.
- **Recálculo**: ante `vehicle.status_changed` (el vehículo sale de
  operación) o desvíos detectados por `telemetry.aggregated`, busca un
  vehículo alternativo y publica `route.recalculated` o `route.unassignable`.
- **Navegación**: expone el contrato de la app del conductor (paradas
  ordenadas, ventanas, ETA) sin exponer datos de clientes.

## Eventos que consume

| Evento                 | Efecto                                                  |
| ---------------------- | ------------------------------------------------------- |
| `shipment.created`     | Primera optimización y asignación de vehículo           |
| `telemetry.aggregated` | Ajuste de ETA si el desvío supera el umbral (15 min)    |
| `vehicle.status_changed` | Recálculo si el vehículo pasa a en_mantenimiento/fuera_de_servicio |

## Eventos que publica

| Evento                 | Cuándo                                                   |
| ---------------------- | -------------------------------------------------------- |
| `route.assigned`       | Tras la primera asignación                               |
| `route.recalculated`   | Recálculo con vehículo alternativo o ETA ajustado        |
| `route.unassignable`   | Ningún vehículo viable (saga de cancelación)             |

## Arquitectura interna

Se replican las convenciones del stack (sección de arquitectura del README
raíz): FastAPI + SQLAlchemy 2.0 asíncrono + Alembic, patrón Outbox con relay
cercano a Redis/RabbitMQ, consumidor idempotente por `processed_events`,
logs JSON correlacionados y métricas Prometheus (`routing_*`).

Todo lo externo entra por **interfaces** de dominio (ISP/DIP), sin
dependencias en el núcleo:

- `ProveedorMapas` (`app/proveedores_mapa.py`): `SimuladoProveedorMapas`
  (determinista, dev/demo y tests) o `MapboxProveedorMapas` (Directions API).
  Si el proveedor cae, se conserva la última ruta y el ETA pasa a
  `estimado` (no se deja la carga sin asignar).
- `ClienteFleet` (`app/cliente_fleet.py`): REST síncrono con timeout,
  reintentos y *circuit breaker*; `ClienteFleetFake` en tests y demo.
- `EtaCache` (`app/cache_redis.py`): caché de ETAs en Redis **opcional**. Si
  Redis cae, se sirve de `routing_db` y el servicio sigue arriba.

## Reglas de dominio

- Capacidad de carga (kg y m³): restricción dura.
- Ventanas horarias de entrega: restricción dura; un vehículo que no llega
  dentro de la ventana no es viable.
- Descanso obligatorio: pausa de 45 min por cada 4,5 h de conducción
  (EU 561/2006 simplificada) sobre la duración bruta del proveedor.

## Desarrollo local

```powershell
# desde este directorio con el venv del proyecto activo
$env:BUS_HABILITADO="false"; $env:REDIS_HABILITADO="false"
$env:DATABASE_URL="sqlite+aiosqlite:///routing_dev.db"
alembic upgrade head
uvicorn app.main:app --port 8003
```

Consume/sin broker, inyecta eventos con el endpoint de demo:

> `POST /internal/bus/deliver` solo se monta con `DEMO_BUS_INTERNO=true`
> fuera de producción/Docker (artefacto **local**, nunca en docker-compose).
> Delega en la misma carretera del consumidor, de modo que la
> deduplicación por `event_id` se puede probar entregando el mismo evento dos
> veces.

```powershell
$env:DEMO_BUS_INTERNO="true"
python scripts/datos_prueba.py   # entrega shipment.created, telemetría y estado de vehículo
```

## Pruebas

```powershell
black --check --line-length 100 .
flake8
pytest -q
```

Corren sobre SQLite/aiosqlite y con adaptadores *fake* (Fleet, Mapas, Redis):
no requieren Docker, PostgreSQL ni un broker. Incluyen la prueba de que
`alembic upgrade head` construye el esquema desde cero.

## Docker

```powershell
docker build -t logitrack/routing-service:1.0.0 .
docker run --rm -p 8003:8003 --env-file .env logitrack/routing-service:1.0.0
```

Produce y consume en `logitrack.events` (exchange topic); cola
`routing.inbox`. Los detalles de orquestación están en el `docker-compose.yml`
de la raíz.