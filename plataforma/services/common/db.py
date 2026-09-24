"""Conexión a la base de datos propia del servicio (Database per Service)."""
import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger("db")

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def esperar_db(intentos: int = 60) -> None:
    for intento in range(1, intentos + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            log.warning("Base de datos no disponible (intento %s/%s): %s", intento, intentos, exc)
            time.sleep(2)
    raise RuntimeError("No se pudo conectar a la base de datos")


def db_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
