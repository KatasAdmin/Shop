# db.py
from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from config import DATABASE_URL


def make_async_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

ASYNC_DATABASE_URL = make_async_url(DATABASE_URL)

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def session_scope() -> AsyncSession:
    """
    Єдиний правильний спосіб працювати з AsyncSession:
    - yield session
    - commit якщо все ок
    - rollback якщо помилка
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise