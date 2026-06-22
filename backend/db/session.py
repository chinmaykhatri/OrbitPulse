"""Async session factory and dependency injection helper.

Every database access in the application uses get_db() as a FastAPI dependency,
ensuring proper session lifecycle (open → use → close) with no leaked connections.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.engine import async_engine

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a scoped async session.

    Usage in endpoints:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(SpaceObject))
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
