"""El servicio no arranca desplegado abierto (defecto 1.5).

Antes `api_keys` venía `[]` por defecto y nada lo vigilaba: el mecanismo de
API key existía en seguridad.py pero quedaba desactivado en cualquier
despliegue, mientras la documentación afirmaba que estaba. Un control de
seguridad que existe pero no está enchufado es peor que no tenerlo.

Ahora Settings exige claves cuando el entorno no es de desarrollo: sin ellas,
el servicio ni siquiera importa, así que el contenedor muere en el arranque en
vez de salir abierto por accidente.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_sin_api_keys_en_un_entorno_no_desarrollo_no_arranca():
    """Docker/producción sin claves = no se arranca (eso es lo que fallaba)."""
    with pytest.raises(ValidationError):
        Settings(entorno="docker", api_keys=[])


def test_en_desarrollo_local_sigue_pudiendo_arrancar_sin_claves():
    """El entorno local/development conserva el endpoint abierto a propósito."""
    ajustes = Settings(entorno="local", api_keys=[])
    assert ajustes.api_keys == []


def test_con_claves_configuradas_arranca_en_cualquier_entorno():
    ajustes = Settings(entorno="docker", api_keys=["demo-logitrack"])
    assert ajustes.api_keys == ["demo-logitrack"]


def test_el_cors_por_defecto_es_el_origen_del_frontend():
    """Nada más de `["*"]`: la lista sale de la configuración."""
    ajustes = Settings()
    assert ajustes.cors_origins == [
        "http://localhost:5173",
        "http://localhost:4173",
    ]
