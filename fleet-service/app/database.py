"""Motor asíncrono de SQLAlchemy 2.0 sobre fleet_db."""

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
    kwargs = {"echo": settings.db_echo, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # SQLite solo se usa en los tests: sin pool_pre_ping ni pool real.
        kwargs = {"echo": settings.db_echo}
    return create_async_engine(url, **kwargs)


engine: AsyncEngine = crear_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
