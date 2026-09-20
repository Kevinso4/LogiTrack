"""Endpoints de telemetría (ficha 3.3 del documento)."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import servicios
from app.agregador import Agregador
from app.config import get_settings
from app.database import get_session
from app.errores import ReglaNegocioViolada
from app.events.base import PublicadorEventos
from app.schemas import AgregadoOut, LecturaOut, LoteTelemetria, RecorridoOut, RespuestaIngesta
from app.seguridad import verificar_api_key

router = APIRouter(prefix="/api/v1/telemetria", tags=["telemetria"])


def obtener_publicador(request: Request) -> Optional[PublicadorEventos]:
    return getattr(request.app.state, "publicador", None)


@router.post(
    "",
    response_model=RespuestaIngesta,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verificar_api_key)],
    summary="Ingesta de telemetría en lote",
    description=(
        "Recibe lecturas de los dispositivos embarcados, valida y normaliza "
        "unidades entre fabricantes, persiste en la hypertable y publica "
        "`telemetry.raw`. No realiza análisis: eso es de Routing y Maintenance."
    ),
)
async def ingestar(
    lote: LoteTelemetria,
    session: AsyncSession = Depends(get_session),
    publicador: Optional[PublicadorEventos] = Depends(obtener_publicador),
):
    maximo = get_settings().max_lecturas_por_lote
    if len(lote.lecturas) > maximo:
        raise ReglaNegocioViolada(
            f"El lote supera el máximo de {maximo} lecturas",
            {"recibidas": len(lote.lecturas), "maximo": maximo},
        )
    return await servicios.procesar_lote(session, lote, publicador)


@router.get(
    "/{vehiculo_id}/ultima",
    response_model=LecturaOut,
    summary="Última posición conocida del vehículo",
)
async def ultima(vehiculo_id: str, session: AsyncSession = Depends(get_session)):
    return await servicios.ultima_lectura(session, vehiculo_id)


@router.get(
    "/{vehiculo_id}/recorrido",
    response_model=RecorridoOut,
    summary="Recorrido entre dos fechas",
    description="Incluye distancia recorrida (haversine) y velocidades del tramo.",
)
async def recorrido(
    vehiculo_id: str,
    desde: Optional[datetime] = Query(default=None),
    hasta: Optional[datetime] = Query(default=None),
    limite: int = Query(default=5000, ge=1, le=20000),
    session: AsyncSession = Depends(get_session),
):
    return await servicios.recorrido(session, vehiculo_id, desde, hasta, limite)


@router.post(
    "/agregacion/ejecutar",
    response_model=List[AgregadoOut],
    summary="Forzar el cierre de la ventana de agregación",
    description=(
        "Uso operativo y de demostración: normalmente lo dispara la tarea de "
        "fondo cada `VENTANA_AGREGACION_SEGUNDOS`."
    ),
)
async def ejecutar_agregacion(
    ventana_segundos: Optional[int] = Query(default=None, ge=1, le=86400),
):
    agregador = Agregador(ventana_segundos)
    return await agregador.ejecutar_ventana()
