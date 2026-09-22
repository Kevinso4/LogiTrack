# LogiTrack — hoja de sustentación

Kevin Ayazo · UCC Montería · Ingeniería de Sistemas

---

## 1. Los cinco procesos

| Servicio | Puerto | De qué trata |
|---|---|---|
| **Shipment** | 8004 | Ciclo de vida del envío: creado → asignado → en ruta → entregado, más incidentes. **Mío.** |
| **Routing** | 8003 | Calcula la ruta óptima y elige vehículo. Habla con Mapbox detrás de una interfaz. **Mío.** |
| Fleet | 8001 | Maestro de vehículos y conductores: quién puede mover carga y en qué estado está. |
| Tracking | 8002 | Ingesta de telemetría GPS. El de mayor caudal: recibe, normaliza, guarda y publica. |
| interop-bridge | 8005 | Traductor entre mi contrato y el del Fleet de Juan Camilo. |

Cada servicio tiene **su propia base de datos**. Nadie lee la tabla del otro.

---

## 2. Cómo se conectan

Dos vías, a propósito:

- **REST síncrono** en un solo punto: Routing pregunta a Fleet
  `GET /api/v1/vehiculos/disponibles` antes de asignar. Es síncrono porque
  necesita la respuesta *ahora* para decidir.
- **Eventos asíncronos** para todo lo demás, sobre RabbitMQ (exchange topic
  `logitrack.events`). Nadie orquesta: cada servicio publica lo que le pasó y
  los interesados reaccionan. Eso es la **saga coreografiada**.

### El flujo de la demo

```
Creo un envío
   └─> Shipment publica  shipment.created
         └─> Routing calcula ruta y pregunta a Fleet por vehículo (REST)
Reporto una avería
   └─> Shipment publica  shipment.incident
         └─> Fleet pone el vehículo fuera_de_servicio
               └─> Fleet publica  vehicle.status_changed
                     └─> ese vehículo desaparece de /disponibles
```

Nadie coordinó eso. No hay orquestador.

---

## 3. Los cuatro patrones

**Database per Service.** Cada servicio su base. Acoplarse por la base es el
error clásico que convierte microservicios en un monolito distribuido.

**Outbox.** El cambio de estado y la fila del evento se escriben en la *misma
transacción*; un relay en segundo plano es lo único que habla con RabbitMQ.
Si el broker está caído, el evento espera en la tabla y sale cuando vuelve.
Si el commit falla, no hay evento fantasma.

**Consumidores idempotentes.** Cada `event_id` procesado se guarda en la misma
transacción que el efecto. RabbitMQ garantiza *at-least-once*, así que una
reentrega no cambia dos veces el estado.

**Capa anticorrupción (ACL).** El `interop-bridge` traduce el contrato del
compañero en el borde. Su formato no entra a mi dominio.

---

## 4. Preguntas probables

**¿Por qué microservicios y no un monolito?**
Las cargas son muy distintas: Tracking recibe una lectura por vehículo cada
10 segundos, Shipment unas pocas por hora. Escalarlos juntos obliga a pagar
el pico del peor.

**¿Por qué RabbitMQ y no llamadas HTTP entre servicios?**
Con HTTP, si Fleet se cae, Shipment se cae con él. Con eventos, el mensaje
espera en la cola. Acoplamiento temporal vs. desacoplamiento.

**¿Qué pasa si se publica el evento pero falla la base?**
No puede pasar — ese es el punto del outbox. Evento y estado van en la misma
transacción.

**¿Y si RabbitMQ entrega el mismo mensaje dos veces?**
Se descarta por `event_id`. Lo probé reenviando el mismo evento.

**¿Por qué hay dos Fleet en el repo?**
El mío es dependencia de desarrollo: me deja testear Routing y Shipment
aislados. El de integración es el de mi compañero. Como los contratos
divergieron (sobre del evento, topología de exchanges y vocabulario de
estados), puse un traductor en el borde en vez de contaminar mi dominio.

**¿Qué es SOLID aquí, en concreto?**
`PublicadorEventos`, `ProveedorMapas` y `ClienteFleet` son interfaces. En los
tests uso implementaciones en memoria sin tocar una línea de producción. Eso
es inversión de dependencias y sustitución de Liskov, no teoría.

**¿Qué limitaciones tiene / qué harías distinto?**
*(la respuesta más fuerte que tengo — contarla completa)*
Los 125 tests estaban en verde mientras los consumidores estaban **sordos al
bus**: se rendían ante un `Connection refused` y nunca reintentaban. Eso solo
apareció corriendo el sistema de verdad, no con `pytest`. Agregué reconexión
con backoff exponencial. En el mismo ejercicio encontré cinco fallas más:
el healthcheck de RabbitMQ daba "sano" 20 segundos antes de aceptar
conexiones, los eventos a un exchange sin cola se descartaban en silencio,
la máquina de estados permitía que un envío retrocediera, y los entrypoints
entraban en crash-loop enmascarado por `restart: unless-stopped`.
Falta prueba de carga (k6) y suscriptor MQTT.

---

## 5. Números y comandos

- **164 tests** en verde: 25 Fleet + 27 Tracking + 56 Routing + 44 Shipment
  + 12 bridge. Corren sin Docker, contra SQLite y bus en memoria.
- `black --line-length 100` y `flake8` limpios. CI en GitHub Actions por
  servicio afectado.

```powershell
docker compose --profile interop up -d      # levantar todo
docker compose ps                           # verificar
```

| Qué | Dónde |
|---|---|
| Panel de operaciones | `panel.html` (doble clic) |
| Swagger Routing / Shipment | :8003/docs · :8004/docs |
| Consola RabbitMQ | localhost:15672 — `logitrack` / `logitrack` |
| Contrato de eventos | `CONTRATOS.md` |

---

## 6. Antes de entrar

- [ ] Stack levantado y `docker compose ps` en verde
- [ ] `panel.html` abierto en una pestaña
- [ ] Consola de RabbitMQ abierta en otra
- [ ] Leídos: `shipment-service/app/dominio.py`, `app/events/outbox.py`,
      `routing-service/app/cliente_fleet.py`, `interop-bridge/app/`
