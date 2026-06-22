"""Cache package — Redis connection pool and position/status/lock management."""
from cache.redis_client import get_redis, close_redis
from cache.position_cache import (
    store_positions,
    get_positions,
    store_batch_positions,
    get_all_position_keys,
    clear_positions,
    clear_all_positions,
    set_pipeline_status,
    get_pipeline_status,
    acquire_simulation_lock,
    release_simulation_lock,
    is_simulation_locked,
)

__all__ = [
    "get_redis",
    "close_redis",
    "store_positions",
    "get_positions",
    "store_batch_positions",
    "get_all_position_keys",
    "clear_positions",
    "clear_all_positions",
    "set_pipeline_status",
    "get_pipeline_status",
    "acquire_simulation_lock",
    "release_simulation_lock",
    "is_simulation_locked",
]
