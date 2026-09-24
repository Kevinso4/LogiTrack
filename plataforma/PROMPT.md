# Prompts para LogiTrack

Hay dos prompts. El **1** reconstruye o amplía el sistema completo con cualquier asistente de código
(Claude Code, Cursor, Copilot…). El **2** sirve solo para el frontend en herramientas de UI (v0, Lovable, Bolt).
Cópialos tal cual y ajusta lo que está entre `<...>`.

---

## Prompt 1 — Sistema completo (backend + frontend)

```text
Actúa como ingeniero de software senior especializado en microservicios. Vas a implementar LogiTrack,
una plataforma de gestión de flotas y logística de última milla, para un proyecto universitario de
Ingeniería de Sistemas (Universidad Cooperativa de Colombia). Todo el código, los comentarios, los nombres
de tablas y endpoints y los mensajes de error van en ESPAÑOL; los nombres de eventos van en inglés con
el formato dominio.accion (p. ej. shipment.created).

## Alcance
Seis piezas funcionales y conectadas entre sí:
1. API Gateway   2. Fleet Service   3. Tracking Ingestion Service   4. Shipment Service
5. Maintenance Service   6. Frontend web.
Más un simulador de dispositivos GPS que envíe telemetría para que la demo tenga datos en vivo.

## Stack obligatorio
- Backend: Python 3.12 + FastAPI + SQLAlchemy 2 + Pydantic v2. Un único Dockerfile multi-etapa para todos
  los servicios (build-arg SERVICE), imagen final python:3.12-slim con usuario no root.
- Datos: PostgreSQL 16 con UNA base de datos por servicio (Database per Service). tracking_db usa la
  extensión TimescaleDB con la tabla posiciones como hypertable particionada cada 7 días.
  Ninguna llave foránea cruza servicios: los ids externos son UUID sin FK.
- Mensajería: RabbitMQ (aio-pika), exchange topic durable "logitrack.events", routing key = tipo de evento,
  cada cola con su Dead Letter Queue "<cola>.dlq". Redis para rate limiting y refresh tokens.
- Todo se levanta con `docker compose up --build`. Solo el gateway expone puerto (8000).
- Frontend: Next.js 15 (App Router) + TypeScript + TailwindCSS v4 + MapLibre GL.

## Reglas de comunicación
- REST síncrono SOLO cuando quien llama no puede continuar sin la respuesta: Shipment consulta a Fleet
  GET /api/v1/vehiculos/disponibles?peso_kg=&volumen_m3=&refrigerado=&hazmat=&zona= para asignar vehículo.
  Timeout 2 s, 3 reintentos con backoff exponencial + jitter, circuit breaker (5 fallos en 30 s → abierto 30 s
  → semiabierto).
- Todo lo demás por eventos. Formato: {event_id, tipo, origen, ocurrido_en, datos}.
- Patrón Outbox en todo servicio que publica desde una transacción: la fila de negocio y la fila en
  outbox_eventos se guardan en la MISMA transacción; un proceso de fondo publica y marca publicado_en.
- Consumidores idempotentes: tabla eventos_procesados(event_id PK) en la misma transacción del efecto.
- POST /api/v1/envios acepta la cabecera Idempotency-Key.

## Servicios
### API Gateway
- POST /api/v1/auth/token, /auth/refresh, /auth/logout. JWT RS256 (access 15 min); refresh token de 7 días
  rotativo en cookie HttpOnly SameSite=Strict: reutilizar uno ya usado revoca toda la sesión.
  Contraseñas con Argon2id. Usuarios demo: admin/admin123 (admin), operador/operador123 (operador),
  gestor/gestor123 (gestor_flota), conductor/conductor123 (conductor).
- Proxy por prefijo: vehiculos|conductores|asignaciones → fleet; telemetria|dispositivos → tracking;
  envios → shipment; mantenimiento → maintenance. Reenvía X-User-Id, X-User-Role y X-Request-ID.
- Rate limit por minuto y rol en Redis (operador 600, conductor 300, cliente 120, anónimo 30 por IP) → 429 + Retry-After.
- CORS con lista blanca explícita (nunca *). Formato único de error:
  {"error","mensaje","request_id","timestamp"}.
- GET /api/v1/estado/servicios (ready de cada servicio + circuito) y GET /api/v1/eventos/stream (SSE con
  los eventos de dominio del bus, para el feed en vivo del panel).
- GET /api/v1/envios/seguimiento/{codigo} es público (sin token).

### Fleet Service (fleet_db)
Tablas vehiculos (placa UQ, tipo enum furgon|camion|tractomula|van, capacidad_kg, capacidad_m3, anio,
vencimiento_seguro, estado enum activo|en_transito|en_mantenimiento|fuera_de_servicio, refrigerado,
certificado_hazmat, zona), conductores, conductor_categorias, asignaciones. Índice (estado, tipo, refrigerado).
Endpoints: CRUD de vehículos y conductores, /vehiculos/disponibles, PATCH /vehiculos/{id}/estado,
/vehiculos/resumen, /conductores/{id}/disponibilidad, POST /asignaciones. Datos semilla: 8 vehículos en
Montería, Cartagena, Barranquilla, Medellín y Sincelejo, y 6 conductores.
Publica vehicle.status_changed. Consume: maintenance.alert crítica → en_mantenimiento;
maintenance.completed → activo; shipment.incident (avería/accidente) → fuera_de_servicio;
shipment.assigned/reassigned → en_transito; shipment.delivered/returned → activo.

### Tracking Ingestion Service (tracking_db, TimescaleDB)
POST /api/v1/telemetria recibe lotes (hasta 1000 lecturas: lat, lon, velocidad, combustible, temperatura
de carga, temperatura de motor, odómetro, código OBD2), autentica el dispositivo con X-Device-Key
(solo se guarda el SHA-256), inserta con ON CONFLICT DO NOTHING y publica telemetry.raw y un
telemetry.aggregated por vehículo. No espera a nadie ni analiza nada. Consultas: /telemetria/ultimas,
/{vehiculo_id}/ultima, /{vehiculo_id}/recorrido, /estadisticas.

### Shipment Service (shipment_db)
Tablas envios (código público LT-XXXXXX, cliente, origen/destino con lat/lon, estado enum pendiente|
en_transito|con_incidencia|retrasado|entregado|devuelto, fecha_limite_sla, peso, volumen, refrigeración,
hazmat, internacional, vehiculo_id externo), eventos_envio (solo inserción: cadena de custodia),
pruebas_entrega, outbox_eventos. Índice (estado, fecha_limite_sla).
- POST /envios responde 201 al instante y asigna vehículo en segundo plano (REST a Fleet).
- Saga coreografiada: POST /envios/{id}/incidencia → shipment.incident → Fleet saca el vehículo →
  vehicle.status_changed → Shipment busca otro vehículo → shipment.reassigned. Compensación: si no hay
  vehículo, el envío pasa a retrasado, se libera la carga y se publica shipment.delayed.
  Un proceso reintenta cada 15 s los envíos pendientes o retrasados.
- También: /prueba-entrega (→ shipment.delivered), /reanudar, /devolucion (→ shipment.returned),
  /asignar, /historial, /resumen (incluye envíos en riesgo de SLA y % de cumplimiento).

### Maintenance Service (maintenance_db)
Tablas reglas (métrica, operador mayor|menor|presente, umbral, prioridad 1-3), alertas, programas_mantenimiento,
intervenciones (solo inserción). Consume telemetry.aggregated: evalúa reglas (motor > 105 °C y código OBD2 =
críticas; velocidad > 110; carga refrigerada > 8 °C; combustible < 10 %), no duplica alertas abiertas y publica
maintenance.alert con "critica". Programa automáticamente un mantenimiento preventivo cada 10 000 km / 60 días
(maintenance.scheduled). POST /intervenciones cierra las alertas del vehículo y publica maintenance.completed.

### Todos los servicios
/health y /ready (BD + broker), logs JSON en una línea con request_id, shipment_id y vehicle_id,
validación Pydantic (422), RBAC por rol en cada endpoint de escritura, consultas parametrizadas.

## Frontend (lenguaje visual de Apple)
Sigue las Human Interface Guidelines de Apple: fondo #f5f5f7, tarjetas blancas con radio de 20 px y sombra
muy suave, tipografía del sistema (-apple-system / SF Pro, Inter como respaldo), títulos grandes de 34 px en
negrita con tracking negativo, color de acento #0071e3, colores semánticos del sistema (verde, naranja, rojo,
índigo), barra lateral translúcida con backdrop-filter blur, barra de pestañas inferior en móvil, controles
segmentados, interruptores estilo iOS, hojas modales que suben desde abajo, avisos tipo píldora, animaciones
con curva cubic-bezier(0.32, 0.72, 0, 1), modo oscuro automático y respeto a prefers-reduced-motion.
Páginas: Login (con cuentas demo), Resumen (métricas, mapa en vivo, feed de eventos en vivo por SSE, estado
de la plataforma), Seguimiento (mapa a pantalla completa, lista de vehículos, telemetría y recorrido del
vehículo seleccionado), Envíos (lista filtrable, crear envío, detalle con cadena de custodia y acciones:
incidencia, entrega, reanudar, devolver), Flota (tarjetas de vehículos, cambio de estado, asignar conductor,
conductores), Mantenimiento (alertas, próximos servicios con barra de progreso por km, historial, reglas
editables) y una página pública /seguimiento para rastrear por código sin sesión.
El access token vive en memoria; la sesión se recupera con la cookie de refresh al recargar.

## Entregables
Código completo y ejecutable, docker-compose.yml, infra/postgres/init.sql, un workflow de GitHub Actions por
servicio (disparado con paths:, lint con ruff, pip-audit, gitleaks, build y push a GHCR etiquetado con el SHA,
despliegue a Render: develop → staging, main → producción con aprobación manual) y un README con cómo
ejecutarlo y un guion de demostración de los flujos. Verifica que todo arranque y que cada flujo funcione
de punta a punta antes de darlo por terminado.
```

---

## Prompt 2 — Solo el frontend (v0 / Lovable / Bolt)

```text
Diseña el panel web de LogiTrack, una plataforma de gestión de flotas de transporte en Colombia, con el
lenguaje visual de Apple (macOS Sonoma / iOS 17): Next.js + TypeScript + TailwindCSS, todo en español.

Estilo: fondo #f5f5f7 (negro puro en modo oscuro), tarjetas blancas (#1c1c1e en oscuro) con radio de 20 px,
borde de 0.5 px casi invisible y sombra muy suave; tipografía -apple-system/SF Pro con Inter de respaldo;
títulos grandes (34 px, bold, tracking -0.022em); acento #0071e3; colores de estado: verde disponible,
azul en tránsito, naranja mantenimiento, rojo fuera de servicio. Barra lateral translúcida (blur 20 px,
saturate 180 %) con iconos lineales tipo SF Symbols y el ítem activo como píldora azul; en móvil, barra de
pestañas inferior. Controles segmentados, interruptores iOS, hojas modales que suben desde abajo, avisos tipo
píldora arriba al centro, badges redondeados con punto de color, esqueletos de carga, animaciones cortas
con cubic-bezier(0.32,0.72,0,1). Nada de gradientes llamativos ni sombras duras: sobrio, aireado, preciso.

Pantallas:
1. Login centrado con logo, campos agrupados en una sola tarjeta y accesos rápidos a cuentas demo.
2. Resumen: saludo según la hora y fecha, 4 métricas (vehículos disponibles, envíos en tránsito, alertas
   abiertas, lecturas GPS por segundo), mapa de la flota con marcadores tipo píldora (punto de color + placa),
   feed "Actividad en vivo" con los eventos del sistema, barras de flota y envíos por estado, estado de los
   microservicios con latencia.
3. Seguimiento: lista de vehículos a la izquierda y mapa grande; al elegir uno, tarjeta flotante translúcida
   con velocidad, combustible, temperatura de motor, odómetro y el recorrido de los últimos 30 minutos.
4. Envíos: control segmentado por estado con contadores, buscador, lista con código, ruta, vehículo, SLA
   (naranja si está en riesgo) y estado; hoja para crear envío (cliente, origen/destino de una lista de
   ciudades, peso, volumen, fecha límite, interruptores refrigeración/hazmat) y hoja de detalle con la cadena
   de custodia como línea de tiempo y acciones (reportar incidencia, registrar entrega, reanudar, devolver).
5. Flota: tarjetas de vehículo (placa grande, marca, conductor, capacidad, iconos de refrigerado/hazmat,
   badge de estado) y pestaña de conductores; detalle con telemetría, cambio de estado y asignación de conductor.
6. Mantenimiento: métricas, pestañas Alertas / Próximos servicios (barra de progreso por km) / Historial /
   Reglas (umbral editable e interruptor para activar), y hoja para registrar una intervención.
7. Página pública "Rastrea tu envío." con buscador por código y progreso Recibido → En camino → Entregado.

Consume la API REST en NEXT_PUBLIC_API_URL (http://localhost:8000) con JWT Bearer; usa datos de ejemplo
mientras no haya backend.
```
