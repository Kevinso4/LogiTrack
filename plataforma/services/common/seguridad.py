"""RBAC dentro de cada servicio (no solo en el gateway).

El gateway valida el JWT y reenvía la identidad en las cabeceras X-User-Id y X-User-Role.
Las llamadas internas servicio-a-servicio viajan por la red privada con X-User-Role: servicio.
"""
from typing import Annotated

from fastapi import Depends, Header

from .errores import error

ROLES = ("admin", "operador", "gestor_flota", "conductor", "cliente", "servicio")
SIEMPRE_PERMITIDOS = ("admin", "servicio")


def rol_actual(x_user_role: Annotated[str | None, Header()] = None) -> str:
    if not x_user_role or x_user_role not in ROLES:
        raise error(401, "no_autenticado", "Falta la identidad del usuario")
    return x_user_role


def requiere_rol(*roles: str):
    def dependencia(rol: Annotated[str, Depends(rol_actual)]) -> str:
        if rol in SIEMPRE_PERMITIDOS or rol in roles:
            return rol
        raise error(403, "sin_permiso", f"El rol '{rol}' no puede realizar esta acción")

    return Depends(dependencia)
