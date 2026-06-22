"""Database engine factory — async for application, sync for Alembic.

Uses asyncpg for all runtime queries (non-blocking).
Sync engine is only used by Alembic migrations, never by application code.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine

from config import get_settings

settings = get_settings()

async_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

# Alembic requires a sync engine — convert the async URL
_sync_url = settings.database_url.replace("+asyncpg", "")
engine = create_engine(_sync_url, echo=False)
