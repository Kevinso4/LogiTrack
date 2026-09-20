"""Motor asíncrono sobre tracking_db (PostgreSQL + TimescaleDB).

Perfil de escalado propio: muchas conexiones cortas de escritura. Por eso el
pool es más grande que el de un servicio transaccional normal.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def crear_engine(url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = url or settings.database_url
    if url.startswith("sqlite"):
        return create_async_engine(url, echo=settings.db_echo)
    return create_async_engine(
        url,
        echo=settings.db_echo,
        pool_size=20,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=1800,
    )


engine: AsyncEngine = crear_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
