# Tracking Ingestion Service

Ingesta de telemetría GPS de LogiTrack (ficha 3.3 del documento de
arquitectura). Es el servicio de mayor caudal del sistema: una lectura por
vehículo cada 10 segundos. **Recibe, valida, normaliza, guarda y publica.
Nada más** — el análisis es de Routing y de Maintenance.

- Puerto `8002` · base `tracking_db` (PostgreSQL + TimescaleDB) · FastAPI async
- Publica `telemetry.raw` y `telemetry.aggregated`
- No consume ningún evento

## Arranque rápido

```bash
pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8002
python scripts/simulador_iot.py --vehiculos 5     # dispositivos simulados
pytest -q                                         # 27 tests, sin Docker
```

## Normalización entre fabricantes

`app/normalizacion.py` define un perfil por fabricante: alias de campos y
unidades de origen. Todo se traduce a **km/h, °C, km y %** antes de tocar la
base.

| Perfil | Velocidad | Temperatura | Odómetro | Campos |
|---|---|---|---|---|
| `generico` | km/h | °C | km | canónicos |
| `queclink` | mph | °F | millas | `latitude`, `speed`, `engine_temp`… |
| `teltonika` | km/h | °C | metros | `lat`, `lng`, `spd`, `odo`, `dtc` |
| `concox` | nudos | °C | km | canónicos, combustible en fracción |

El campo `unidades` del lote permite sobrescribir el perfil por petición.

Una lectura inválida se rechaza con motivo tipificado y **no tumba el lote**:
`campo_faltante`, `coordenada_invalida`, `velocidad_fuera_de_rango`,
`combustible_fuera_de_rango`, `timestamp_futuro`, `timestamp_antiguo`,
`timestamp_invalido`, `valor_no_numerico`, `unidad_desconocida`.

## Persistencia

Hypertable `telemetry` particionada por `time` en chunks de 7 días
(`CHUNK_DIAS`). La clave primaria `(vehicle_id, time)` incluye la columna de
partición —requisito de TimescaleDB— y hace la ingesta idempotente: un lote
reenviado no duplica filas (`ON CONFLICT DO NOTHING`), y la respuesta lo
reporta en `duplicadas`.

Si el PostgreSQL de destino no tiene la extensión TimescaleDB, la migración
avisa y deja una tabla normal: el servicio funciona igual, sin particionado
automático.

## Agregación

Cada `VENTANA_AGREGACION_SEGUNDOS` (60 por defecto) una tarea de fondo cierra
la ventana y publica un `telemetry.aggregated` por vehículo, con velocidad
media y máxima, temperatura máxima de motor, combustible, odómetro, distancia
recorrida, horas de motor y códigos OBD2 del período. Ese es el evento que
consumen Routing (desvíos de ruta) y Maintenance (umbrales de motor).

Para forzarlo en una demo: `POST /api/v1/telemetria/agregacion/ejecutar`.

Detalle completo de endpoints y decisiones de diseño: `../README.md`.
