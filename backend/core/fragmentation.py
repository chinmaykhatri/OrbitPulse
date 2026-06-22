"""Fragmentation simulation — NASA breakup model for Kessler syndrome visualization.

Simulates a satellite breakup event by generating fragment objects with
velocity vectors drawn from the NASA Standard Breakup Model distribution.

The NASA model specifies that fragment velocities follow a log-normal
distribution with parameters dependent on the parent object's mass and
the breakup event type (collision vs. explosion). For our visualization,
we use the collision model with configurable mean and cap velocities.

Fragment velocity distribution:
  v = exp(μ + σ × Z)
  where Z ~ N(0,1), μ = ln(mean_velocity), σ = 0.4 (empirical)

Fragments are assigned synthetic NORAD IDs starting at -1000 to avoid
collision with real catalog IDs. Each fragment has a lifetime (expiry)
after which the cleanup task removes it from Redis and the database.

The simulation is protected by a Redis lock — only one simulation can
run at a time. This prevents concurrent fragmentation events from
overwhelming the position cache.
"""
import logging
import math
from datetime import datetime, timezone, timedelta

import numpy as np
from sqlalchemy import select, delete

from config import get_settings
from db.session import AsyncSessionLocal
from db.models import SpaceObject, FragmentationEvent
from core.propagator import propagate_single, PropagationError
from cache.position_cache import (
    acquire_simulation_lock,
    release_simulation_lock,
    store_positions,
    clear_positions,
)

logger = logging.getLogger("orbitpulse.core.fragmentation")
settings = get_settings()

# Starting ID for synthetic fragment NORAD IDs (negative to avoid collision)
_FRAGMENT_ID_BASE = -1000


def _generate_fragment_velocities(
    parent_velocity: np.ndarray,
    count: int,
    mean_ms: float,
    cap_ms: float,
) -> np.ndarray:
    """Generate fragment velocity vectors using NASA breakup model distribution.

    Each fragment gets a velocity perturbation added to the parent's velocity.
    The perturbation magnitude follows a log-normal distribution, and the
    direction is uniformly distributed on the unit sphere.

    Args:
        parent_velocity: Parent object's velocity vector (km/s)
        count: Number of fragments to generate
        mean_ms: Mean fragment ejection velocity (m/s)
        cap_ms: Maximum fragment ejection velocity (m/s)

    Returns:
        Array of shape (count, 3) with fragment velocities in km/s.
    """
    rng = np.random.default_rng()

    # Log-normal velocity magnitudes (NASA model: σ ≈ 0.4)
    mu = math.log(mean_ms)
    sigma = 0.4
    magnitudes_ms = np.minimum(
        rng.lognormal(mean=mu, sigma=sigma, size=count),
        cap_ms,
    )
    magnitudes_kms = magnitudes_ms / 1000.0

    # Uniform random directions on the unit sphere
    theta = rng.uniform(0, 2 * math.pi, count)
    phi = np.arccos(rng.uniform(-1, 1, count))
    directions = np.column_stack([
        np.sin(phi) * np.cos(theta),
        np.sin(phi) * np.sin(theta),
        np.cos(phi),
    ])

    # Fragment velocity = parent velocity + perturbation
    perturbations = directions * magnitudes_kms[:, np.newaxis]
    fragment_velocities = parent_velocity[np.newaxis, :] + perturbations

    return fragment_velocities


async def simulate_fragmentation(
    norad_id: int,
    fragment_count: int | None = None,
) -> dict | None:
    """Simulate a satellite breakup event.

    Steps:
      1. Acquire simulation lock (Redis, 5 min expiry)
      2. Get parent satellite's current state (position + velocity)
      3. Generate fragment velocity vectors (NASA breakup model)
      4. For each fragment:
         a. Assign a synthetic NORAD ID
         b. Compute a short propagation (position in TEME at current time)
         c. Store position in Redis cache
      5. Record the event in the database
      6. Release simulation lock

    Args:
        norad_id: NORAD ID of the satellite to fragment
        fragment_count: Number of fragments (default from config, max 200)

    Returns:
        Dict with fragments_generated, synthetic_ids, parent_norad_id.
        Returns None if the satellite doesn't exist or lock can't be acquired.
    """
    if fragment_count is None:
        fragment_count = settings.default_fragment_count
    fragment_count = min(fragment_count, settings.max_fragment_count)

    # Acquire lock — only one simulation at a time
    if not await acquire_simulation_lock():
        logger.warning("Simulation lock held — concurrent fragmentation blocked")
        return None

    try:
        # Get parent satellite TLE from database
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SpaceObject).where(SpaceObject.norad_id == norad_id)
            )
            parent = result.scalar_one_or_none()

        if parent is None or not parent.tle_line1 or not parent.tle_line2:
            logger.warning(f"Cannot fragment NORAD {norad_id} — not found or missing TLE")
            return None

        # Get parent's current state
        now = datetime.now(timezone.utc)
        try:
            parent_pos, parent_vel = propagate_single(
                parent.tle_line1, parent.tle_line2, now,
            )
        except PropagationError as e:
            logger.error(f"Cannot propagate parent satellite {norad_id}: {e}")
            return None

        # Generate fragment velocities
        fragment_vels = _generate_fragment_velocities(
            parent_velocity=parent_vel,
            count=fragment_count,
            mean_ms=settings.fragment_velocity_mean_ms,
            cap_ms=settings.fragment_velocity_cap_ms,
        )

        # Generate fragment positions (small offset from parent)
        rng = np.random.default_rng()
        position_offsets = rng.normal(0, 0.01, size=(fragment_count, 3))
        fragment_positions = parent_pos[np.newaxis, :] + position_offsets

        # Assign synthetic IDs and store
        expiry = now + timedelta(minutes=settings.fragment_expiry_minutes)
        synthetic_ids: list[int] = []

        async with AsyncSessionLocal() as session:
            # Find the lowest existing fragment ID to avoid collisions
            existing = await session.execute(
                select(FragmentationEvent.fragment_norad_id).order_by(
                    FragmentationEvent.fragment_norad_id
                ).limit(1)
            )
            lowest = existing.scalar_one_or_none()
            start_id = min(_FRAGMENT_ID_BASE, (lowest or 0) - 1) - fragment_count

            for i in range(fragment_count):
                frag_id = start_id - i
                synthetic_ids.append(frag_id)

                # Store single-point position in Redis
                # Shape (1, 3) — just the current position for globe display
                pos_array = fragment_positions[i].reshape(1, 3)
                await store_positions(frag_id, pos_array)

                # Record in database
                event = FragmentationEvent(
                    parent_norad_id=norad_id,
                    fragment_norad_id=frag_id,
                    spawned_at=now,
                    expires_at=expiry,
                )
                session.add(event)

            await session.commit()

        logger.info(
            f"Fragmentation simulated: {fragment_count} fragments from "
            f"NORAD {norad_id}, IDs {synthetic_ids[0]} to {synthetic_ids[-1]}, "
            f"expires at {expiry.isoformat()}"
        )

        return {
            "fragments_generated": fragment_count,
            "synthetic_ids": synthetic_ids,
            "parent_norad_id": norad_id,
        }

    finally:
        await release_simulation_lock()


async def cleanup_fragments(norad_id: int | None = None) -> int:
    """Remove expired or specific fragment data.

    If norad_id is provided, removes all fragments from that parent.
    If norad_id is None, removes all fragments past their expiry time.

    Cleans up both the database records and the Redis position cache.

    Returns count of fragments removed.
    """
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        if norad_id is not None:
            # Remove all fragments from a specific parent
            result = await session.execute(
                select(FragmentationEvent.fragment_norad_id).where(
                    FragmentationEvent.parent_norad_id == norad_id
                )
            )
        else:
            # Remove all expired fragments
            result = await session.execute(
                select(FragmentationEvent.fragment_norad_id).where(
                    FragmentationEvent.expires_at < now
                )
            )

        fragment_ids = [row[0] for row in result.all()]

        if not fragment_ids:
            return 0

        # Clear Redis cache for each fragment
        for fid in fragment_ids:
            await clear_positions(fid)

        # Delete database records
        if norad_id is not None:
            await session.execute(
                delete(FragmentationEvent).where(
                    FragmentationEvent.parent_norad_id == norad_id
                )
            )
        else:
            await session.execute(
                delete(FragmentationEvent).where(
                    FragmentationEvent.expires_at < now
                )
            )

        await session.commit()

    logger.info(f"Cleaned up {len(fragment_ids)} fragment(s)")
    return len(fragment_ids)
