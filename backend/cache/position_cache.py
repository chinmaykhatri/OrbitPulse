"""Position cache — binary NumPy array storage in Redis.

Stores propagated position arrays (shape: N_timesteps × 3, TEME frame)
as binary blobs using np.save/np.load. This is 10x smaller and 100x faster
to deserialize than JSON serialization.

Also manages pipeline status broadcasting and simulation locks.

Key naming convention:
  pos:{norad_id}     — position array for one satellite
  pos:metadata       — propagation metadata (reserved)
  sim:lock           — fragmentation simulation lock (5 min expiry)
  pipeline:status    — current pipeline stage and progress
"""
import io
import json
import logging

import numpy as np

from cache.redis_client import get_redis

logger = logging.getLogger("orbitpulse.cache.positions")

POSITION_KEY_PREFIX = "pos:"
METADATA_KEY = "pos:metadata"
SIMULATION_LOCK_KEY = "sim:lock"
PIPELINE_STATUS_KEY = "pipeline:status"


async def store_positions(norad_id: int, positions: np.ndarray) -> None:
    """Store position array for a single object.

    Args:
        norad_id: NORAD catalog ID
        positions: shape (N_timesteps, 3) array in TEME frame (km)
    """
    redis = await get_redis()
    buf = io.BytesIO()
    np.save(buf, positions)
    await redis.set(f"{POSITION_KEY_PREFIX}{norad_id}", buf.getvalue())


async def get_positions(norad_id: int) -> np.ndarray | None:
    """Retrieve position array for a single object.

    Returns None if no cached positions exist (object not yet propagated
    or cache was flushed).
    """
    redis = await get_redis()
    data = await redis.get(f"{POSITION_KEY_PREFIX}{norad_id}")
    if data is None:
        return None
    buf = io.BytesIO(data)
    return np.load(buf)


async def store_batch_positions(positions_dict: dict[int, np.ndarray]) -> None:
    """Store positions for multiple objects in a single Redis pipeline.

    Uses pipelining to avoid 25,000 round trips. Each pipeline.set() is
    buffered and sent as one batch to Redis.

    Args:
        positions_dict: {norad_id: positions_array} mapping
    """
    redis = await get_redis()
    pipe = redis.pipeline()
    for norad_id, positions in positions_dict.items():
        buf = io.BytesIO()
        np.save(buf, positions)
        pipe.set(f"{POSITION_KEY_PREFIX}{norad_id}", buf.getvalue())
    await pipe.execute()
    logger.info(f"Batch-stored positions for {len(positions_dict)} objects")


async def get_all_position_keys() -> list[int]:
    """Get all NORAD IDs that have cached positions.

    Uses SCAN (not KEYS) to avoid blocking Redis on large keyspaces.
    """
    redis = await get_redis()
    norad_ids = []
    async for key in redis.scan_iter(match=f"{POSITION_KEY_PREFIX}*"):
        key_str = key.decode() if isinstance(key, bytes) else key
        if key_str == METADATA_KEY:
            continue
        try:
            norad_id = int(key_str.replace(POSITION_KEY_PREFIX, ""))
            norad_ids.append(norad_id)
        except ValueError:
            continue
    return norad_ids


async def clear_positions(norad_id: int) -> None:
    """Remove cached positions for a single object."""
    redis = await get_redis()
    await redis.delete(f"{POSITION_KEY_PREFIX}{norad_id}")


async def clear_all_positions() -> int:
    """Remove all cached positions. Returns count of keys removed."""
    redis = await get_redis()
    keys = []
    async for key in redis.scan_iter(match=f"{POSITION_KEY_PREFIX}*"):
        keys.append(key)
    if keys:
        await redis.delete(*keys)
    return len(keys)


# --- Pipeline Status ---

async def set_pipeline_status(stage: str, progress_pct: float) -> None:
    """Update pipeline status for WebSocket broadcast.

    Called by each pipeline stage (ingestion, propagation, detection)
    to report progress to connected frontend clients.
    """
    redis = await get_redis()
    await redis.set(
        PIPELINE_STATUS_KEY,
        json.dumps({"stage": stage, "progress_pct": round(progress_pct, 1)}),
    )


async def get_pipeline_status() -> dict | None:
    """Get current pipeline stage and progress percentage."""
    redis = await get_redis()
    data = await redis.get(PIPELINE_STATUS_KEY)
    if data is None:
        return None
    return json.loads(data)


# --- Simulation Lock ---

async def acquire_simulation_lock() -> bool:
    """Acquire exclusive simulation lock. Returns True if acquired.

    Uses Redis SET NX (set-if-not-exists) with a 5-minute expiry.
    Only one fragmentation simulation can run at a time.
    """
    redis = await get_redis()
    acquired = await redis.set(SIMULATION_LOCK_KEY, "1", nx=True, ex=300)
    if acquired:
        logger.info("Simulation lock acquired")
    else:
        logger.warning("Simulation lock already held — concurrent simulation blocked")
    return bool(acquired)


async def release_simulation_lock() -> None:
    """Release the simulation lock."""
    redis = await get_redis()
    await redis.delete(SIMULATION_LOCK_KEY)
    logger.info("Simulation lock released")


async def is_simulation_locked() -> bool:
    """Check if a simulation is currently running."""
    redis = await get_redis()
    return await redis.exists(SIMULATION_LOCK_KEY) > 0
