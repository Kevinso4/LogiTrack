"""Lógica de negocio del Routing Service.

Una sola razón de cambio: cómo se calculan y asignan rutas óptimas (SRP,
sección 5e). Depende de las interfaces `ClienteFleet` y `ProveedorMapas`
(DIP), nunca de httpx ni del SDK de Mapbox.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache_redis import EtaCache
from app.cliente_fleet import ClienteFleet, ClienteFleetREST, FleetNoDisponible
from app.config import get_settings
from app.dominio import ESTADOS_ACTIVOS, EstadoRuta
from app.errores import RecursoNoEncontrado
from app.events.outbox import registrar_evento
from app.models import IntentoAsignacion, Parada, Ruta
from app.observabilidad import log, rutas_calculadas
from app.proveedores_mapa import (
    ErrorProveedorExterno,
    PuntoParada,
    ProveedorMapas,
    fabricar_proveedor,
)
from app.reglas_ruta import (
    capacidad_cumplida,
    duracion_con_descansos,
    etas_por_parada,
    ventana_cumplida_por_todas,
)
from app.schemas import ShipmentCreatedPayload, TelemetryAggregatedPayload

logger = logging.getLogger(__name__)

EVENTO_ASIGNADA = "route.assigned"
EVENTO_RECALCULADA = "route.recalculated"
EVENTO_NO_ASIGNABLE = "route.unassignable"

# Estados de Fleet (vehicle.status_changed) que obligan a sacar el vehículo de
# las rutas activas. en_transito/activo no.
_ESTADOS_FUERA = {"en_mantenimiento", "fuera_de_servicio"}


# --------------------------------------------------------------------------
# Adaptadores de frontera (inyección simple, sin framework).
# --------------------------------------------------------------------------
_cliente_fleet_actual: Optional[ClienteFleet] = None
_proveedor_mapa_actual: Optional[ProveedorMapas] = None
_cache_eta_actual: Optional[EtaCache] = None


def configurar_adaptadores(
    cliente_fleet: Optional[ClienteFleet] = None,
    proveedor_mapa: Optional[ProveedorMapas] = None,
    cache_eta: Optional[EtaCache] = None,
) -> None:
    """Sustituye los adaptadores del puerto de salida (los tests usan fakes;
    LSP: mismo contrato, distinta implementación)."""
    global _cliente_fleet_actual, _proveedor_mapa_actual, _cache_eta_actual
    _cliente_fleet_actual = cliente_fleet
    _proveedor_mapa_actual = proveedor_mapa
    _cache_eta_actual = cache_eta


def cliente_fleet() -> ClienteFleet:
    global _cliente_fleet_actual
    if _cliente_fleet_actual is None:
        _cliente_fleet_actual = ClienteFleetREST(get_settings().fleet_url)
    return _cliente_fleet_actual


def proveedor_mapa() -> ProveedorMapas:
    global _proveedor_mapa_actual
    if _proveedor_mapa_actual is None:
        _proveedor_mapa_actual = fabricar_proveedor()
    return _proveedor_mapa_actual


def cache_eta() -> EtaCache:
    global _cache_eta_actual
    if _cache_eta_actual is None:
        _cache_eta_actual = EtaCache()
    return _cache_eta_actual


# --------------------------------------------------------------------------
# Utilidades de la frontera interna.
# --------------------------------------------------------------------------
def _paradas_desde_envio(payload: ShipmentCreatedPayload) -> List[Dict]:
    return [
        {
            "direccion": payload.origen.direccion,
            "lat": payload.origen.lat,
            "lng": payload.origen.lon,
            "ventana_desde": None,
            "ventana_hasta": None,
        },
        {
            "direccion": payload.destino.direccion,
            "lat": payload.destino.lat,
            "lng": payload.destino.lon,
            "ventana_desde": (payload.ventana_entrega.desde if payload.ventana_entrega else None),
            "ventana_hasta": (payload.ventana_entrega.hasta if payload.ventana_entrega else None),
        },
    ]


def _paradas_desde_ruta(ruta: Ruta) -> List[Dict]:
    """Reconstruye las paradas desde la ruta persistida (sin JOIN a otros
    dominios: Shipment no expone su estado por SQL)."""
    origen, destino = ruta.origen, ruta.destino
    ventana = destino.get("ventana_entrega") or None
    ventana_desde = ventana_hasta = None
    if ventana is not None:
        ventana_desde = datetime.fromisoformat(ventana["desde"]) if ventana.get("desde") else None
        ventana_hasta = datetime.fromisoformat(ventana["hasta"]) if ventana.get("hasta") else None
    return [
        {
            "direccion": origen.get("direccion", ""),
            "lat": origen.get("lat"),
            "lng": origen.get("lon"),
            "ventana_desde": None,
            "ventana_hasta": None,
        },
        {
            "direccion": destino.get("direccion", ""),
            "lat": destino.get("lat"),
            "lng": destino.get("lon"),
            "ventana_desde": ventana_desde,
            "ventana_hasta": ventana_hasta,
        },
    ]


def _destino_con_ventana(payload: ShipmentCreatedPayload) -> dict:
    destino = payload.destino.model_dump(mode="json")
    if payload.ventana_entrega is not None:
        destino["ventana_entrega"] = payload.ventana_entrega.model_dump(mode="json")
    return destino


async def _registrar_intento(
    session: AsyncSession,
    ruta: Ruta,
    causa: str,
    vehicle_anterior: Optional[str],
    fallido: bool,
    motivo: Optional[str],
) -> None:
    session.add(
        IntentoAsignacion(
            ruta_id=ruta.id,
            shipment_id=ruta.shipment_id,
            causa=causa,
            vehicle_anterior=vehicle_anterior,
            fallido=fallido,
            motivo=motivo,
        )
    )


async def _persistir_paradas(
    session: AsyncSession, ruta: Ruta, paradas: List[Dict], etas: List[datetime]
) -> None:
    await session.execute(delete(Parada).where(Parada.ruta_id == ruta.id))
    for i, p in enumerate(paradas):
        session.add(
            Parada(
                ruta_id=ruta.id,
                orden=i,
                direccion=p["direccion"],
                lat=p["lat"],
                lng=p["lng"],
                ventana_desde=p.get("ventana_desde"),
                ventana_hasta=p.get("ventana_hasta"),
                eta_llegada=etas[i] if i < len(etas) else None,
            )
        )


async def _marcar_no_asignable(
    session: AsyncSession,
    ruta: Ruta,
    causa: str,
    motivo: str,
    hacer_commit: bool = True,
) -> Ruta:
    ruta.estado = EstadoRuta.NO_ASIGNABLE.value
    ruta.motivo = motivo
    await _registrar_intento(session, ruta, causa, ruta.vehicle_id, True, motivo)
    registrar_evento(
        session,
        EVENTO_NO_ASIGNABLE,
        {
            "ruta_id": ruta.id,
            "shipment_id": ruta.shipment_id,
            "motivo": motivo,
            "causa": causa,
        },
    )
    rutas_calculadas.labels("no_asignable").inc()
    if hacer_commit:
        await session.commit()
    return ruta


async def _calcular_y_fijar(
    session: AsyncSession,
    ruta: Ruta,
    vehiculo,
    paradas: List[Dict],
    causa: str,
    como_recalculada: bool = False,
    hacer_commit: bool = True,
) -> Ruta:
    """Consulta al proveedor de mapas, valida ventana y fija vehículo + ETA.

    Si el proveedor de mapas falla, conserva la última ruta y marca el ETA como
    estimado (sección 5f): la carga NO se queda sin asignar por un tercero.
    """
    settings = get_settings()
    puntos = [PuntoParada(lat=p["lat"], lng=p["lng"]) for p in paradas]
    try:
        resultado = await proveedor_mapa().optimizar_ruta(puntos)
    except ErrorProveedorExterno as exc:
        log(logger, logging.WARNING, "mapas.fallo", ruta_id=ruta.id, error=str(exc))
        resultado = None

    tipo = "calculado" if resultado is not None else "estimado"
    if resultado is not None:
        distancia = resultado.distancia_km
        duracion = duracion_con_descansos(
            resultado.duracion_min,
            settings.limite_conduccion_min,
            settings.pausa_descanso_min,
        )
    else:
        # Sin proveedor: línea recta entre paradas a velocidad de crucero.
        distancia = ruta.distancia_km if ruta.distancia_km else 0.0
        duracion = distancia / settings.velocidad_estimacion_kmh * 60 if distancia else 120.0

    inicio = datetime.now(timezone.utc)
    etas = etas_por_parada(len(paradas), inicio, duracion)
    ventanas_hasta = [p.get("ventana_hasta") for p in paradas]
    if not ventana_cumplida_por_todas(etas, ventanas_hasta):
        return await _marcar_no_asignable(
            session,
            ruta,
            causa="ventana_incumplible",
            motivo="la ventana de entrega no es alcanzable con este vehículo",
            hacer_commit=hacer_commit,
        )

    ruta.vehicle_id = vehiculo.id
    ruta.vehicle_plate = vehiculo.plate
    ruta.estado = EstadoRuta.RECALCULADA.value if como_recalculada else EstadoRuta.ASIGNADA.value
    ruta.distancia_km = distancia
    ruta.duracion_min = duracion
    ruta.eta_actual = etas[-1]
    ruta.tipo_calculo = tipo
    ruta.motivo = causa
    if como_recalculada:
        ruta.intentos_recalculo += 1
    await _persistir_paradas(session, ruta, paradas, etas)

    await cache_eta().guardar(ruta.id, ruta.eta_actual)
    evento = EVENTO_RECALCULADA if como_recalculada else EVENTO_ASIGNADA
    registrar_evento(
        session,
        evento,
        {
            "ruta_id": ruta.id,
            "shipment_id": ruta.shipment_id,
            "vehicle_id": vehiculo.id,
            "vehicle_plate": vehiculo.plate,
            "eta": ruta.eta_actual.isoformat(),
            "distancia_km": ruta.distancia_km,
            "duracion_min": ruta.duracion_min,
            "tipo_calculo": tipo,
            "motivo": causa,
        },
    )
    rutas_calculadas.labels(ruta.estado).inc()
    if hacer_commit:
        await session.commit()
    return ruta


# --------------------------------------------------------------------------
# Operaciones de negocio.
# --------------------------------------------------------------------------
async def asignar_ruta(
    session: AsyncSession, payload: ShipmentCreatedPayload, hacer_commit: bool = True
) -> Ruta:
    """Primera asignación: consulta a Fleet y publica route.assigned.

    Idempotente: si el shipment ya tiene ruta, no crea una segunda (una
    reentrega de shipment.created no duplica el efecto).
    """
    existente = await session.scalar(select(Ruta).where(Ruta.shipment_id == payload.shipment_id))
    if existente is not None:
        return existente

    ruta = Ruta(
        shipment_id=payload.shipment_id,
        origen=payload.origen.model_dump(mode="json"),
        destino=_destino_con_ventana(payload),
        peso_kg=payload.peso_kg,
        volumen_m3=payload.volumen_m3,
        requiere_refrigeracion=payload.requiere_refrigeracion,
        requiere_hazmat=payload.requiere_hazmat,
        estado=EstadoRuta.PENDIENTE.value,
    )
    session.add(ruta)
    await session.flush()  # necesitamos ruta.id

    paradas = _paradas_desde_envio(payload)
    try:
        vehiculos = await cliente_fleet().buscar_disponibles(
            capacidad_min_kg=payload.peso_kg,
            volumen_min_m3=payload.volumen_m3,
            refrigerado=payload.requiere_refrigeracion,
            hazmat=payload.requiere_hazmat,
        )
    except FleetNoDisponible as exc:
        # Fleet caído: la ruta queda pendiente y se reintenta en el siguiente
        # evento; NO se publica route.unassignable (compensarías envíos buenos).
        log(
            logger,
            logging.WARNING,
            "fleet.no_disponible",
            shipment_id=payload.shipment_id,
            error=str(exc),
        )
        ruta.motivo = "pendiente: fleet no accesible"
        await _registrar_intento(
            session, ruta, "shipment.created", None, False, "fleet_no_disponible"
        )
        if hacer_commit:
            await session.commit()
        return ruta

    if not vehiculos:
        return await _marcar_no_asignable(
            session,
            ruta,
            causa="sin_vehiculo_viable",
            motivo="ningún vehículo disponible cumple la carga",
            hacer_commit=hacer_commit,
        )

    vehiculo = vehiculos[0]
    if not capacidad_cumplida(
        vehiculo.capacity_kg, vehiculo.capacity_m3, payload.peso_kg, payload.volumen_m3
    ):
        return await _marcar_no_asignable(
            session,
            ruta,
            causa="capacidad_insuficiente",
            motivo=f"vehículo {vehiculo.plate} no cumple la capacidad exigida",
            hacer_commit=hacer_commit,
        )

    return await _calcular_y_fijar(
        session,
        ruta,
        vehiculo,
        paradas,
        causa="asignacion_inicial",
        hacer_commit=hacer_commit,
    )


async def recalcular_ruta(
    session: AsyncSession,
    ruta_id: str,
    causa: str,
    excluir_vehicle_id: Optional[str] = None,
    hacer_commit: bool = True,
) -> Ruta:
    """Recálculo: busca un vehículo alternativo y publica route.recalculated o
    route.unassignable (saga de reasignación, sección 3)."""
    ruta = await session.get(Ruta, ruta_id)
    if ruta is None:
        raise RecursoNoEncontrado(f"No existe la ruta {ruta_id}")
    if EstadoRuta(ruta.estado) not in ESTADOS_ACTIVOS:
        # Pandada o no-asignable: no hay nada que recalcular.
        return ruta

    paradas = _paradas_desde_ruta(ruta)
    try:
        vehiculos = await cliente_fleet().buscar_disponibles(
            capacidad_min_kg=ruta.peso_kg,
            volumen_min_m3=ruta.volumen_m3,
            refrigerado=ruta.requiere_refrigeracion,
            hazmat=ruta.requiere_hazmat,
        )
    except FleetNoDisponible as exc:
        # Fleet caído: se conserva la ruta actual (el ETA ya informado sigue
        # valiendo) y se reintenta con el próximo evento de Fleet.
        log(
            logger,
            logging.WARNING,
            "fleet.no_disponible_recalculo",
            ruta_id=ruta.id,
            error=str(exc),
        )
        return ruta

    candidatos = [v for v in vehiculos if v.id != excluir_vehicle_id]
    if not candidatos:
        return await _marcar_no_asignable(
            session,
            ruta,
            causa=causa,
            motivo="sin vehículo alternativo disponible",
            hacer_commit=hacer_commit,
        )
    return await _calcular_y_fijar(
        session,
        ruta,
        candidatos[0],
        paradas,
        causa=causa,
        como_recalculada=True,
        hacer_commit=hacer_commit,
    )


async def actualizar_por_telemetria(
    session: AsyncSession,
    agregado: TelemetryAggregatedPayload,
    hacer_commit: bool = True,
) -> Optional[Ruta]:
    """Desvío de ruta detectado por telemetry.aggregated.

    Estimación deliberadamente simple: desplaza el ETA según el déficit de
    velocidad del vehículo respecto de la planificada, sobre la ventana que
    reporta Tracking. Solo publica route.recalculated si el desvío supera el
    umbral configurado (evita spam de eventos).
    """
    ruta = await session.scalar(
        select(Ruta)
        .where(
            Ruta.vehicle_id == agregado.vehicle_id,
            Ruta.estado.in_([s.value for s in ESTADOS_ACTIVOS]),
        )
        .order_by(Ruta.actualizada_en.desc())
        .limit(1)
    )
    if ruta is None or ruta.eta_actual is None or not ruta.duracion_min:
        return None

    settings = get_settings()
    plan_kmh = (
        ruta.distancia_km / (ruta.duracion_min / 60)
        if ruta.distancia_km
        else settings.velocidad_estimacion_kmh
    )
    vel = agregado.velocidad_promedio_kmh
    if vel is None or vel <= 0:
        return None

    ventana_min = max((agregado.ventana_fin - agregado.ventana_inicio).total_seconds() / 60, 0.1)
    desvio_min = 0.0
    if vel < plan_kmh:
        desvio_min = ventana_min * (1 - vel / plan_kmh)
    if agregado.detenido:
        desvio_min = max(desvio_min, ventana_min)

    if desvio_min <= settings.umbral_desvio_min:
        return None

    nueva_eta = ruta.eta_actual + timedelta(minutes=desvio_min)
    ruta.eta_actual = nueva_eta
    ruta.tipo_calculo = "estimado"
    ruta.motivo = "desvio_de_ruta"
    await cache_eta().guardar(ruta.id, nueva_eta)
    registrar_evento(
        session,
        EVENTO_RECALCULADA,
        {
            "ruta_id": ruta.id,
            "shipment_id": ruta.shipment_id,
            "vehicle_id": ruta.vehicle_id,
            "vehicle_plate": ruta.vehicle_plate,
            "eta": nueva_eta.isoformat(),
            "distancia_km": ruta.distancia_km,
            "duracion_min": ruta.duracion_min,
            "tipo_calculo": "estimado",
            "motivo": "desvio_telemetria",
        },
    )
    log(
        logger,
        logging.INFO,
        "ruta.eta_recalculada",
        ruta_id=ruta.id,
        desvio_min=desvio_min,
    )
    if hacer_commit:
        await session.commit()
    return ruta
