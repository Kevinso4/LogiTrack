"""Traducción pura entre dialectos (seam 2 del PROMPT_INTEGRACION).

Aquí NO hay I/O: solo transformaciones sobre diccionarios, todas idempotentes
y cubiertas por tests. El sobre del compañero es `{event_id, tipo,
ocurrido_en, origen, agregado_id, datos}`; el propio es `{event_id,
event_type, occurred_at, producer, trace_id, payload}` (CONTRATOS.md).

Principios de la capa anticorrupción:
  * `event_id` viaja intacto en ambas direcciones.
  * `trace_id` no existe en el dialecto del compañero: el puente lo genera
    (o lo conserva si llega) y lo propaga en los headers del mensaje.
  * un estado o campo desconocido se reenvía tal cual (passthrough), jamás
    se descarta.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.base import EventoDominio
from app.interop import traducir_estado_vehiculo

# Únicos eventos que el puente conoce (las colas solo se suscriben a estos).
EVENTO_ENTRANTE = "vehicle.status_changed"   # de ellos hacia nosotros
EVENTO_SALIENTE = "shipment.incident"        # de nosotros hacia ellos
EVENTO_TELEMETRIA = "telemetry.aggregated"   # de nosotros hacia su Maintenance

# Sobres: qué clave nuestra equivale a cada clave del compañero.
SOBRE_COMPANERO_A_PROPIOS = {
    "event_id": "event_id",
    "tipo": "event_type",
    "ocurrido_en": "occurred_at",
    "origen": "producer",
    "datos": "payload",
}
SOBRE_PROPIOS_A_COMPANERO = {v: k for k, v in SOBRE_COMPANERO_A_PROPIOS.items()}

# vehicle.status_changed: datos del compañero -> payload propio
# (`estado_*` pasa por la tabla de equivalencias de `app.interop`).
DATOS_ENTRANTES_A_PROPIOS = {
    "vehiculo_id": "vehicle_id",
    "placa": "plate",
    "estado_anterior": "estado_anterior",
    "estado_nuevo": "estado_nuevo",
    "motivo": "motivo",
    "zona_operacion": "zona",
}

# telemetry.aggregated: payload propio -> datos del compañero.
#
# Los nombres de destino NO son una elección: salen del diccionario CAMPOS
# de su maintenance-service/app/events/consumer.py, que es literalmente lo
# que su motor de reglas busca en el evento. Un nombre distinto aquí no da
# error: simplemente la métrica se salta y la alerta nunca se abre.
PAYLOAD_TELEMETRIA_A_COMPANERO = {
    "vehicle_id": "vehiculo_id",
    "temperatura_motor_max_c": "temperatura_max_c",
    "odometro_km": "km_acumulados",
    "horas_motor": "horas_motor",
    "combustible_pct": "nivel_combustible_pct",
}

# shipment.incident: payload propio -> datos del compañero.
PAYLOAD_SALIENTES_A_COMPANERO = {
    "vehicle_id": "vehiculo_id",
    "shipment_id": "envio_id",
    "tipo": "tipo",
    "confirmado": "confirmado",
    "motivo": "motivo",
}


def _renombrar(origen: Dict[str, Any], mapa: Dict[str, str]) -> Dict[str, Any]:
    """Renombra claves presentes según `mapa`, en el orden del mapa."""
    traducidos: Dict[str, Any] = {}
    for clave, destino in mapa.items():
        if clave in origen:
            traducidos[destino] = origen[clave]
    return traducidos


def _parsear_ocurrido_en(valor: Any) -> datetime:
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def clave_agregado(event_type: str, payload: Dict[str, Any]) -> Optional[str]:
    """El identificador del agregado que el compañero espera en el sobre."""
    if event_type.startswith("shipment."):
        return payload.get("shipment_id")
    if event_type.startswith("vehicle.") or event_type.startswith("telemetry."):
        return payload.get("vehicle_id")
    return None


def traducir_datos_entrantes(datos: Dict[str, Any]) -> Dict[str, Any]:
    """datos (compañero) -> payload (propio), traduciendo los estados."""
    payload = _renombrar(datos, DATOS_ENTRANTES_A_PROPIOS)
    for clave in ("estado_anterior", "estado_nuevo"):
        if clave in payload:
            payload[clave] = traducir_estado_vehiculo(payload[clave], a_propio=True)
    return payload


def traducir_entrante(
    sobre_comp: Dict[str, Any], *, trace_id: Optional[str] = None
) -> EventoDominio:
    """Sobre del compañero (logitrack.fleet) -> EventoDominio propio.

    El compañero no trae `trace_id` en el sobre; se genera uno y el llamador
    lo propaga en los headers AMQP (ver `app.bus`).
    """
    if trace_id is None:
        trace_id = uuid.uuid4().hex
    return EventoDominio(
        event_id=sobre_comp.get("event_id") or uuid.uuid4().hex,
        event_type=sobre_comp.get("tipo") or EVENTO_ENTRANTE,
        occurred_at=_parsear_ocurrido_en(sobre_comp.get("ocurrido_en")),
        producer=sobre_comp.get("origen") or "companero",
        trace_id=trace_id,
        payload=traducir_datos_entrantes(sobre_comp.get("datos") or {}),
    )


def traducir_datos_salientes(payload: Dict[str, Any]) -> Dict[str, Any]:
    """payload (propio) -> datos (compañero), solo claves del contrato."""
    return _renombrar(payload, PAYLOAD_SALIENTES_A_COMPANERO)


def traducir_saliente(evento: EventoDominio) -> Dict[str, Any]:
    """EventoDominio propio (logitrack.events) -> sobre del compañero."""
    return {
        "event_id": evento.event_id,
        "tipo": evento.event_type,
        "ocurrido_en": evento.occurred_at.isoformat().replace("+00:00", "Z"),
        "origen": evento.producer,
        "agregado_id": clave_agregado(evento.event_type, evento.payload),
        "datos": traducir_datos_salientes(evento.payload),
    }


def traducir_datos_telemetria(payload: Dict[str, Any]) -> Dict[str, Any]:
    """payload propio -> datos del compañero, solo las métricas que él evalúa.

    Se descartan los valores `None`. No es cosmética: su consumidor hace
    `if valor is None: continue`, así que mandar la clave vacía y no mandarla
    producen el mismo resultado, y omitirla deja el mensaje más limpio de leer
    cuando haya que depurar por qué no se abrió una alerta.

    El resto del agregado (velocidades, distancia, códigos OBD2, última
    posición) no se envía: su Maintenance no lo mira. Mandar campos que el
    receptor ignora es ruido que luego alguien tiene que descartar a mano.
    """
    datos = _renombrar(payload, PAYLOAD_TELEMETRIA_A_COMPANERO)
    return {clave: valor for clave, valor in datos.items() if valor is not None}


def traducir_telemetria_saliente(evento: EventoDominio) -> Dict[str, Any]:
    """`telemetry.aggregated` propio -> sobre del compañero (logitrack.tracking).

    Va por su propia función y no por `traducir_saliente` porque el mapa de
    campos es distinto: comparten el sobre, no el contenido.
    """
    return {
        "event_id": evento.event_id,
        "tipo": evento.event_type,
        "ocurrido_en": evento.occurred_at.isoformat().replace("+00:00", "Z"),
        "origen": evento.producer,
        "agregado_id": evento.payload.get("vehicle_id"),
        "datos": traducir_datos_telemetria(evento.payload),
    }
