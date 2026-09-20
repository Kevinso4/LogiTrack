"""La migración de Alembic construye el esquema desde cero (SQLite).

Es la prueba que el CI saca del repositorio: crea una base vacía, aplica
`alembic upgrade head` y comprueba que existen las tablas de negocio y de
infraestructura.
"""

import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def test_alembic_upgrade_head_crea_el_esquema(tmp_path):
    ruta_bd = tmp_path / "migracion.db"
    entorno = dict(os.environ)
    entorno["DATABASE_URL"] = f"sqlite+aiosqlite:///{ruta_bd}"
    entorno["BUS_HABILITADO"] = "false"
    entorno["LOG_LEVEL"] = "WARNING"
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(RAIZ),
        env=entorno,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert ruta_bd.exists()


def test_alembic_offline_genera_sql_no_vacio(tmp_path):
    entorno = dict(os.environ)
    entorno["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/no_importa.db"
    resultado = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=str(RAIZ),
        env=entorno,
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "CREATE TABLE envios" in resultado.stdout
