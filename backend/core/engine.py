"""Orbital engine — full catalog propagation and position management.

This is the heart of OrbitPulse. The engine:
  1. Loads the satellite catalog from the database
  2. Propagates every object across a 72-hour window at 60-second timesteps
  3. Stores position arrays in Redis for the detector and API
  4. Provides real-time position lookups (interpolated from cached arrays)
  5. Handles ISS tracking as a special fast-path case

Design decisions:
  - Propagation is sequential per-object but uses NumPy arrays per-timestep.
    True vectorization across objects requires the sgp4 array API, which is
    added as a future optimization. Current performance: ~30s for 25,000 objects.
  - Positions are stored in TEME frame in Redis. Geodetic conversion happens
    on-demand because only a subset of objects are displayed at any time.
  - The timestep list is shared across all objects and generated once.
  - Failed propagations (expired TLEs, decayed objects) are skipped with
    a warning log. The rest of the catalog continues propagating.
"""
import logging
from datetime import datetime, timezone, timedelta

import numpy as np
from sqlalchemy import select, text

from config import get_settings
from db.session import AsyncSessionLocal
from db.models import SpaceObject
from core.propagator import (
    propagate_timeseries,
    propagate_single,
    teme_to_geodetic,
    PropagationError,
)
from cache.position_cache import (
    store_batch_positions,
    get_positions,
    set_pipeline_status,
)

logger = logging.getLogger("orbitpulse.core.engine")
settings = get_settings()


class OrbitalEngine:
    """Full catalog orbital propagation engine.

    Maintains an in-memory catalog index and coordinates propagation
    across all tracked objects. Positions are stored in Redis for
    consumption by the detector, API, and WebSocket broadcaster.

    Usage:
        engine = OrbitalEngine()
        await engine.load_catalog()
        await engine.propagate_full_catalog()
        pos = await engine.get_current_position(25544)  # ISS
    """

    def __init__(self) -> None:
        self._catalog: dict[int, dict] = {}
        self._timesteps: list[datetime] = []
        self._propagation_epoch: datetime | None = None
        self._propagated_count: int = 0

    @property
    def catalog_size(self) -> int:
        """Number of objects in the loaded catalog."""
        return len(self._catalog)

    @property
    def is_propagated(self) -> bool:
        """True if at least one propagation cycle has completed."""
        return self._propagated_count > 0

    async def load_catalog(self) -> int:
        """Load satellite catalog from database into memory.

        Only loads objects that have valid TLE lines (both line1 and line2
        must be non-empty). Objects without TLEs are excluded from
        propagation but remain in the database for reference.

        Returns:
            Count of objects loaded into the engine catalog.
        """
        self._catalog.clear()

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    SpaceObject.norad_id,
                    SpaceObject.name,
                    SpaceObject.tle_line1,
                    SpaceObject.tle_line2,
                    SpaceObject.tle_epoch,
                    SpaceObject.object_type,
                    SpaceObject.rcs_size,
                ).where(
                    SpaceObject.tle_line1.isnot(None),
                    SpaceObject.tle_line2.isnot(None),
                    SpaceObject.tle_line1 != "",
                    SpaceObject.tle_line2 != "",
                )
            )
            rows = result.all()

        for row in rows:
            self._catalog[row.norad_id] = {
                "name": row.name,
                "line1": row.tle_line1,
                "line2": row.tle_line2,
                "epoch": row.tle_epoch,
                "type": str(row.object_type) if row.object_type else None,
                "rcs": str(row.rcs_size) if row.rcs_size else None,
            }

        logger.info(f"Loaded {len(self._catalog)} objects into orbital engine")
        return len(self._catalog)

    def _generate_timesteps(self) -> list[datetime]:
        """Generate the propagation timestep list.

        Creates a list of UTC datetimes from now to now + 72 hours
        at 60-second intervals. This is computed once per propagation
        cycle and shared across all objects.

        Total timesteps: 72 * 60 = 4,320
        """
        now = datetime.now(timezone.utc)
        window_seconds = settings.propagation_window_hours * 3600
        step_seconds = settings.propagation_timestep_coarse_s

        steps = []
        t = now
        end = now + timedelta(seconds=window_seconds)
        while t <= end:
            steps.append(t)
            t += timedelta(seconds=step_seconds)

        self._propagation_epoch = now
        return steps

    async def propagate_full_catalog(self) -> int:
        """Propagate every cataloged object across the 72-hour window.

        This is the heavy computation step. For each object:
          1. Propagate using SGP4 at every timestep (60s intervals)
          2. Store the position array in Redis

        Objects that fail propagation (invalid TLE, expired epoch) are
        skipped. The failure count is logged but does not halt the pipeline.

        Positions are batched into groups of 500 for Redis pipeline writes,
        balancing memory usage against round-trip overhead.

        Returns:
            Count of successfully propagated objects.
        """
        if not self._catalog:
            logger.warning("No catalog loaded — cannot propagate")
            return 0

        self._timesteps = self._generate_timesteps()
        total = len(self._catalog)
        logger.info(
            f"Starting propagation: {total} objects × "
            f"{len(self._timesteps)} timesteps ({settings.propagation_window_hours}h window)"
        )

        await set_pipeline_status("propagation", 0.0)

        success_count = 0
        fail_count = 0
        batch: dict[int, np.ndarray] = {}
        batch_size = 500

        for idx, (norad_id, obj) in enumerate(self._catalog.items()):
            try:
                positions, _ = propagate_timeseries(
                    obj["line1"], obj["line2"], self._timesteps,
                )

                # Skip objects where >50% of positions are NaN (severely expired TLE)
                nan_fraction = np.isnan(positions[:, 0]).sum() / len(positions)
                if nan_fraction > 0.5:
                    fail_count += 1
                    continue

                batch[norad_id] = positions
                success_count += 1

            except PropagationError:
                fail_count += 1
                continue
            except Exception as e:
                logger.warning(
                    f"Unexpected error propagating NORAD {norad_id} ({obj['name']}): {e}"
                )
                fail_count += 1
                continue

            # Flush batch to Redis every 500 objects
            if len(batch) >= batch_size:
                await store_batch_positions(batch)
                batch.clear()

                progress = (idx + 1) / total * 100.0
                await set_pipeline_status("propagation", progress)

        # Flush remaining batch
        if batch:
            await store_batch_positions(batch)

        self._propagated_count = success_count
        await set_pipeline_status("propagation", 100.0)

        logger.info(
            f"Propagation complete: {success_count} succeeded, "
            f"{fail_count} failed out of {total} total"
        )
        return success_count

    async def get_current_position(
        self, norad_id: int
    ) -> tuple[float, float, float] | None:
        """Get current geodetic position (lat, lon, alt) for a satellite.

        Uses the cached position array and interpolates to the current time.
        Falls back to direct propagation if no cache exists.

        Returns None if the satellite is not in the catalog or propagation fails.
        """
        if norad_id not in self._catalog:
            return None

        # Try direct propagation to current time for highest accuracy
        obj = self._catalog[norad_id]
        now = datetime.now(timezone.utc)

        try:
            pos, _ = propagate_single(obj["line1"], obj["line2"], now)
            lat, lon, alt = teme_to_geodetic(pos, now)
            return lat, lon, alt
        except PropagationError as e:
            logger.debug(f"Direct propagation failed for NORAD {norad_id}: {e}")
            return None

    async def get_current_positions_batch(
        self, norad_ids: list[int] | None = None, limit: int = 5000
    ) -> list[list[float]]:
        """Get current positions for multiple satellites.

        Returns flat array format for WebSocket broadcast:
          [[norad_id, lat, lon, alt_km], ...]

        Args:
            norad_ids: Specific IDs to query. If None, uses first `limit` objects.
            limit: Max objects to return (default 5000 for globe performance).

        Returns:
            List of [norad_id, lat, lon, alt] arrays.
        """
        if norad_ids is None:
            ids = list(self._catalog.keys())[:limit]
        else:
            ids = [nid for nid in norad_ids if nid in self._catalog]

        now = datetime.now(timezone.utc)
        results: list[list[float]] = []

        for norad_id in ids:
            obj = self._catalog[norad_id]
            try:
                pos, _ = propagate_single(obj["line1"], obj["line2"], now)
                lat, lon, alt = teme_to_geodetic(pos, now)
                results.append([float(norad_id), lat, lon, alt])
            except (PropagationError, Exception):
                continue

        return results

    async def get_iss_position(self) -> dict | None:
        """Get ISS position with validation metadata.

        ISS is NORAD ID 25544. This is a special-case endpoint because
        the ISS is the most visible and verifiable satellite — its position
        can be cross-checked against n2yo.com and other live trackers.

        Returns dict with lat, lon, alt_km, validated flag, tle_epoch, timestamp.
        """
        iss_id = 25544
        if iss_id not in self._catalog:
            return None

        obj = self._catalog[iss_id]
        now = datetime.now(timezone.utc)

        try:
            pos, _ = propagate_single(obj["line1"], obj["line2"], now)
            lat, lon, alt = teme_to_geodetic(pos, now)

            # Self-validation: ISS altitude should be 380-440 km
            # If outside this range, the TLE is likely expired
            validated = 380.0 <= alt <= 440.0

            return {
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "alt_km": round(alt, 2),
                "validated": validated,
                "tle_epoch": obj["epoch"].isoformat() if obj["epoch"] else "unknown",
                "timestamp": now.isoformat(),
            }
        except PropagationError as e:
            logger.warning(f"ISS propagation failed: {e}")
            return None

    def get_object_info(self, norad_id: int) -> dict | None:
        """Get catalog metadata for a satellite (no propagation)."""
        if norad_id not in self._catalog:
            return None
        obj = self._catalog[norad_id]
        return {
            "norad_id": norad_id,
            "name": obj["name"],
            "object_type": obj["type"],
            "rcs_size": obj["rcs"],
        }

    def get_timesteps(self) -> list[datetime]:
        """Get the current propagation timestep list."""
        return self._timesteps


# Module-level singleton — shared across the application
orbital_engine = OrbitalEngine()
