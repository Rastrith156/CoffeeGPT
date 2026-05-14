from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config import settings
from core.logger import logger


class Base(DeclarativeBase):
    pass


def _async_database_url(url: str) -> str:
    """Convert postgresql:// → postgresql+asyncpg:// for async engine."""
    return url.replace("postgresql://", "postgresql+asyncpg://", 1)


# Fix #17: async engine — does NOT block the event loop
engine = create_async_engine(
    _async_database_url(settings.database_url),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.debug,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db():
    """FastAPI dependency that yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session


def init_db() -> None:
    """
    Fix #13: Schema is managed by Alembic.
    Run `alembic upgrade head` from the backend/ directory to apply migrations.
    This function only validates connectivity at startup.
    """
    logger.info("Database schema managed by Alembic — run: alembic upgrade head")
    ping_database()


def ping_database() -> None:
    """Synchronous connectivity check used at startup via asyncio.to_thread."""
    import sqlalchemy
    sync_url = settings.database_url  # use plain psycopg2 url for ping only
    try:
        engine_sync = sqlalchemy.create_engine(sync_url, pool_pre_ping=True)
        with engine_sync.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine_sync.dispose()
    except Exception as exc:
        logger.warning("Database ping failed (non-fatal at startup): {}", exc)
