"""
Database engine and session factory.

The engine is created from DATABASE_URL in settings.
Changing DATABASE_URL (e.g. from SQLite to PostgreSQL) is the only
thing required to swap databases — no other file needs to change.
"""
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# echo=True prints every SQL statement to the console in development.
# This is helpful for understanding what is happening, but disabled in production.
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """
    Provide a database session to a caller.
    Used as a FastAPI dependency in API routes.
    """
    async with AsyncSessionLocal() as session:
        yield session


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Provide the session factory itself (not an open session).
    Used by streaming routes: they open a session that stays open while the
    stream is sent, because get_session() closes before streaming starts.
    """
    return AsyncSessionLocal


async def create_all_tables() -> None:
    """
    Create all database tables if they do not already exist.
    Called once at application startup.
    """
    from app.core.brain.models import Base  # imported here to avoid circular imports

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
