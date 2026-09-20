"""Autenticación de dispositivos IoT (sección 8 del documento).

API keys rotativas por cabecera `X-API-Key`. En producción esto convive con
mTLS en el borde; aquí queda el control de aplicación. Si no hay claves
configuradas (desarrollo local), el endpoint queda abierto.
"""

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def verificar_api_key(x_api_key: str | None = Header(default=None)) -> None:
    claves = get_settings().api_keys
    if not claves:
        return
    if x_api_key not in claves:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key de dispositivo inválida o ausente",
            headers={"WWW-Authenticate": "ApiKey"},
        )
