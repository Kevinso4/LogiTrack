# Shipment Service

Reina el ciclo de vida del envío de principio a fin. Es el cuarto servicio
del stack LogiTrack (puerto `8004`, base `shipment_db`). Nada más en el stack
conoce esta vida completa; Routing y Fleet solo ven el contratito de cada
evento.

## Responsabilidades

- **Creación**: `POST /api/v1/envios` persiste el envío y publica
  `shipment.created` (inicio de la saga): es la fuente del contrato que
  Routing y Customs consumen.
- **Puesta en ruta**: al recibir `route.assigned`, el envío pasa a `en_ruta`
  con el ETA del vehículo.
- **Recalibración**: `route.recalculated` actualiza vehículo/ETA;
  `route.unassignable` pasa el envío a `retrasado` y publica
  `shipment.delayed`.
- **Aduana**: `customs.held` y `customs.cleared` traban/liberan el envío
  (retención en aduana). Desvío deliberado de la matriz, documentado en el
  README raíz: además de los eventos de ruta, el shipment escucha Custom.
- **Incidentes**: `POST /incidente` confirmado publica `shipment.incident`
  (qué consume Fleet para dejar el vehículo fuera de servicio), y el recálculo
  de la ruta vuelve por `route.recalculated`.
- **Entrega y devolución**: con prueba de entrega (POD) publica
  `shipment.delivered` o `shipment.returned`.

## Eventos que consume

| Evento                 | Transición de estado               |
| ---------------------- | ---------------------------------- |
| `route.assigned`       | en_almacen -> en_ruta              |
| `route.recalculated`   | vehículo/ETA actualizados          |
| `route.unassignable`   | en_ruta -> retrasado (+ delayed)   |
| `customs.held`         | en_ruta -> retenido_aduanera       |
| `customs.cleared`      | retenido_aduanera -> en_ruta       |

## Eventos que publica

| Evento                 | Cuándo                                             |
| ---------------------- | -------------------------------------------------- |
| `shipment.created`     | Alta de un envío (contrato en el README raíz)      |
| `shipment.delivered`   | Entrega con POD                                    |
| `shipment.incident`    | Incidente confirmado (avería/accidente, etc.)      |
| `shipment.returned`    | Devolución                                         |
| `shipment.delayed`     | Sin vehículo viable (route.unassignable)           |

## Máquina de estados

Toda transición pasa por `app/dominio.py`. Estados: `en_almacen`, `en_ruta`,
`retrasado`, `incidente`, `retenido_aduanera`, `entregado`, `retornado`. Las
transiciones inválidas se rechazan (422). El historial es inmutable
(`historial_envios`).

## Desarrollo local

```powershell
# desde este directorio con el venv del proyecto activo
$env:BUS_HABILITADO="false"
$env:DATABASE_URL="sqlite+aiosqlite:///shipment_dev.db"
alembic upgrade head
uvicorn app.main:app --port 8004
```

Crear un envío y pulsar la saga sin broker (endpoint de demo):

> `POST /internal/bus/deliver` solo se monta con `DEMO_BUS_INTERNO=true`
> fuera de producción/Docker (artefacto **local**, nunca en docker-compose).
> Delega en la misma carretera del consumidor: entregar dos veces el mismo
> evento no duplica la transición (idempotencia real).

```powershell
$env:DEMO_BUS_INTERNO="true"
python scripts/datos_prueba.py
```

## Pruebas

```powershell
black --check --line-length 100 .
flake8
pytest -q
```

Corren sobre SQLite/aiosqlite y con el bus en memoria; incluyen la prueba de
que `alembic upgrade head` construye el esquema desde cero.

## Docker

```powershell
docker build -t logitrack/shipment-service:1.0.0 .
docker run --rm -p 8004:8004 --env-file .env logitrack/shipment-service:1.0.0
```

Produce y consume en `logitrack.events` (exchange topic); cola
`shipment.inbox`. Los detalles de orquestación están en el `docker-compose.yml`
de la raíz.