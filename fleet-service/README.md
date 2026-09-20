# Fleet Service

Maestro de vehículos y conductores de LogiTrack (ficha 3.2 del documento de
arquitectura). Responsabilidad única: **quién puede mover una carga y en qué
estado está**. No sabe de rutas, envíos ni facturas.

- Puerto `8001` · base `fleet_db` (PostgreSQL 16) · FastAPI + SQLAlchemy 2.0 async
- Publica `vehicle.status_changed`
- Consume `maintenance.alert` y `shipment.incident`

## Arranque rápido

```bash
pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8001
python scripts/seed.py          # datos de prueba
pytest -q                       # 25 tests, sin Docker
```

Sin broker a mano: `BUS_HABILITADO=false`.

## Piezas

| Archivo | Qué hace |
|---|---|
| `app/dominio.py` | Estados del vehículo y transiciones legales |
| `app/servicios.py` | Lógica de negocio (disponibilidad, cambios de estado, horas de conducción) |
| `app/events/outbox.py` | Escritura atómica del evento + relay al bus |
| `app/events/manejadores.py` | Consumo idempotente de `maintenance.alert` y `shipment.incident` |
| `app/events/rabbitmq.py` | Publicador y consumidor con DLQ |
| `app/routers/` | Endpoints REST |

## Reglas de negocio implementadas

- **Disponible** = estado `activo` + seguro vigente + cumple tipo, zona,
  capacidad y certificaciones (refrigerado / hazmat).
- Un vehículo `fuera_de_servicio` solo vuelve a operar pasando por
  `en_mantenimiento`.
- Cambiar al mismo estado no genera un segundo evento (idempotencia).
- Conductor disponible = activo + licencia vigente + por debajo del tope
  semanal de conducción (`HORAS_MAX_CONDUCCION_SEMANA`, 56 h por defecto).
- `maintenance.alert` con severidad alta/crítica → `en_mantenimiento`.
- `shipment.incident` de tipo avería/accidente confirmado → `fuera_de_servicio`.

Detalle completo de endpoints y decisiones de diseño: `../README.md`.
