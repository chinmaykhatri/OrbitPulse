"""Redis connection pool — singleton pattern with graceful lifecycle.

Uses decode_responses=False because we store binary NumPy array data.
The pool is created lazily on first access and closed explicitly at shutdown.
"""
import logging

import redis.asyncio as redis

from config import get_settings

logger = logging.getLogger("orbitpulse.cache.redis")
settings = get_settings()

_redis_pool: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis connection pool.

    Returns the singleton Redis client. Thread-safe because FastAPI's
    event loop is single-threaded.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            decode_responses=False,
            max_connections=20,
        )
        logger.info("Redis connection pool created")
    return _redis_pool


async def close_redis() -> None:
    """Close the Redis connection pool. Called during application shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.close()
        _redis_pool = None
        logger.info("Redis connection pool closed")
