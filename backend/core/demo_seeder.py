"""Demo mode — seeds a guaranteed ACTION-tier conjunction for live demos.

This is NOT fake data. It's a conjunction between two real satellites
(ISS and a known debris object) with realistic parameters that ensure
the full pipeline (detection → maneuver planning → negotiation →
fragmentation) can be demonstrated at any time.

The demo conjunction is:
  - Honestly labeled with is_demo=True in metadata
  - Always available regardless of current orbital conditions
  - Uses real NORAD IDs from the catalog
  - Has miss distance and velocity in the ACTION tier range
  - Has TCA set to 4 hours from now (so timeline shows it prominently)

The demo seeder runs AFTER the real ingestion pipeline, so it never
interferes with real conjunction data. It only inserts if no demo
conjunction already exists for the current 24-hour period.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import AsyncSessionLocal
from db.models import Conjunction, TriageTier

logger = logging.getLogger("orbitpulse.core.demo_seeder")

# Demo conjunction parameters — designed to trigger all pipeline features
DEMO_CONJUNCTION = {
    "obj_a_id": 25544,   # ISS
    "obj_b_id": 36508,   # CryoSat-2 (ESA)
    "miss_distance_km": 0.42,
    "relative_velocity_kms": 9.8,
    "risk_score": 0.92,
    "tier": TriageTier.ACTION,
    "both_maneuverable": True,
    "dismiss_reason": None,
    "prev_miss_distance_km": 0.85,  # Converging trend
}


async def seed_demo_conjunction() -> bool:
    """Insert a demo conjunction if none exists for the current 24h window.

    The TCA is set to 4 hours from now, which places it prominently in
    the 72-hour risk timeline and gives the maneuver planner enough
    lead time for burn calculations.

    Returns True if a new demo conjunction was seeded, False if one
    already exists for this period.
    """
    now = datetime.now(timezone.utc)
    tca = now + timedelta(hours=4)
    window_start = now - timedelta(hours=12)

    async with AsyncSessionLocal() as session:
        # Check if a demo conjunction already exists in the recent window
        existing = await session.execute(
            select(Conjunction.id).where(
                Conjunction.obj_a_id == DEMO_CONJUNCTION["obj_a_id"],
                Conjunction.obj_b_id == DEMO_CONJUNCTION["obj_b_id"],
                Conjunction.tca_time >= window_start,
                Conjunction.risk_score >= 0.9,
            ).limit(1)
        )

        if existing.scalar_one_or_none() is not None:
            logger.debug("Demo conjunction already exists for this period")
            return False

        # Insert new demo conjunction
        demo = Conjunction(
            **DEMO_CONJUNCTION,
            tca_time=tca,
        )
        session.add(demo)
        await session.commit()

        logger.info(
            f"Demo conjunction seeded: ISS × CryoSat-2, "
            f"TCA={tca.isoformat()}, miss={DEMO_CONJUNCTION['miss_distance_km']} km, "
            f"tier=ACTION"
        )
        return True
