"""Ingestion pipeline — fetches CelesTrak + Space-Track data and upserts into the database.

This is the core data pipeline that runs:
  1. On startup (via main.py lifespan handler)
  2. Every 6 hours (via APScheduler, configured in config.ingestion_interval_hours)

Pipeline stages:
  1. Fetch GP catalog JSON from CelesTrak (primary, includes metadata)
  2. If GP catalog fails, fall back to raw TLE text fetch + parse
  3. Upsert space objects into PostgreSQL (ON CONFLICT UPDATE)
  4. Optionally fetch supplemental data from Space-Track.org
  5. Seed satellite profiles for key satellites (ISS, Starlink samples, etc.)
  6. Report pipeline status via Redis for WebSocket broadcast

Data source hierarchy:
  - CelesTrak (primary): Free, no auth, ~25,000 active objects
  - Space-Track.org (supplemental): Free account, ~50,000 objects, optional

The pipeline is resilient: if CelesTrak is down, it logs the failure
and returns 0 (no objects ingested). Space-Track failures are non-fatal.
The server continues running with whatever data was previously in the database.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import AsyncSessionLocal
from db.models import SpaceObject, SatelliteProfile, ObjectType, RCSSize
from ingestion.celestrak_client import fetch_gp_catalog, fetch_tle_data, CelesTrakError
from ingestion.tle_parser import parse_tle_text
from cache.position_cache import set_pipeline_status

logger = logging.getLogger("orbitpulse.ingestion.pipeline")


# Key satellites to seed with operator profiles for maneuver planning.
# These profiles enable the Tsiolkovsky fuel cost calculation and
# the negotiation protocol's utility function evaluation.
SEED_PROFILES: list[dict] = [
    {
        "norad_id": 25544,
        "operator_name": "NASA/Roscosmos (ISS)",
        "fuel_remaining_pct": 85.0,
        "fuel_remaining_kg": 900.0,
        "dry_mass_kg": 420000.0,
        "mission_priority": 10,
        "maneuver_budget_ms": 100.0,
        "isp_rating": 316.0,
        "remaining_mission_days": 2190,
    },
    {
        "norad_id": 48274,
        "operator_name": "ISRO (Chandrayaan Relay)",
        "fuel_remaining_pct": 60.0,
        "fuel_remaining_kg": 45.0,
        "dry_mass_kg": 1200.0,
        "mission_priority": 8,
        "maneuver_budget_ms": 30.0,
        "isp_rating": 305.0,
        "remaining_mission_days": 1825,
    },
    {
        "norad_id": 43013,
        "operator_name": "NOAA (NOAA-20/JPSS-1)",
        "fuel_remaining_pct": 70.0,
        "fuel_remaining_kg": 80.0,
        "dry_mass_kg": 2200.0,
        "mission_priority": 9,
        "maneuver_budget_ms": 40.0,
        "isp_rating": 220.0,
        "remaining_mission_days": 2555,
    },
    {
        "norad_id": 36508,
        "operator_name": "ESA (CryoSat-2)",
        "fuel_remaining_pct": 40.0,
        "fuel_remaining_kg": 25.0,
        "dry_mass_kg": 720.0,
        "mission_priority": 7,
        "maneuver_budget_ms": 20.0,
        "isp_rating": 290.0,
        "remaining_mission_days": 1095,
    },
    {
        "norad_id": 39084,
        "operator_name": "JAXA (ALOS-2/DAICHI-2)",
        "fuel_remaining_pct": 55.0,
        "fuel_remaining_kg": 60.0,
        "dry_mass_kg": 2100.0,
        "mission_priority": 7,
        "maneuver_budget_ms": 25.0,
        "isp_rating": 280.0,
        "remaining_mission_days": 1460,
    },
]


def _map_object_type(gp_type: str | None) -> ObjectType:
    """Map CelesTrak OBJECT_TYPE string to our enum.

    CelesTrak uses several variations: 'PAYLOAD', 'ROCKET BODY',
    'DEBRIS', 'TBA', 'UNKNOWN'. We normalize to our three-value enum.
    """
    if gp_type is None:
        return ObjectType.DEBRIS
    upper = gp_type.upper().strip()
    if upper == "PAYLOAD":
        return ObjectType.PAYLOAD
    if upper in ("ROCKET BODY", "R/B"):
        return ObjectType.ROCKET_BODY
    return ObjectType.DEBRIS


def _map_rcs_size(gp_size: str | None) -> RCSSize | None:
    """Map CelesTrak RCS_SIZE string to our enum.

    Returns None for unknown/missing values rather than guessing.
    """
    if gp_size is None:
        return None
    upper = gp_size.upper().strip()
    if upper == "SMALL":
        return RCSSize.SMALL
    if upper == "MEDIUM":
        return RCSSize.MEDIUM
    if upper == "LARGE":
        return RCSSize.LARGE
    return None


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse ISO date string from GP catalog. Returns None for missing/null values."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_tle_epoch(line1: str) -> datetime | None:
    """Extract epoch datetime from TLE line 1.

    Reuses the same logic as tle_parser._parse_epoch but with error wrapping.
    """
    try:
        from ingestion.tle_parser import _parse_epoch
        return _parse_epoch(line1)
    except (ValueError, IndexError):
        return None


async def _upsert_objects_from_gp(catalog: list[dict]) -> int:
    """Bulk upsert space objects from GP catalog JSON.

    Uses PostgreSQL's INSERT ... ON CONFLICT DO UPDATE for atomic upserts.
    Each object's TLE lines, metadata, and epoch are updated in place.

    Returns the count of objects upserted.
    """
    if not catalog:
        return 0

    async with AsyncSessionLocal() as session:
        count = 0
        # Process in batches of 1000 to avoid memory pressure
        batch_size = 1000
        for i in range(0, len(catalog), batch_size):
            batch = catalog[i:i + batch_size]
            values = []
            for entry in batch:
                norad_id = entry.get("NORAD_CAT_ID")
                if norad_id is None:
                    continue

                tle_line1 = entry.get("TLE_LINE1", "")
                source = entry.get("_DATA_SOURCE", "celestrak")
                values.append({
                    "norad_id": int(norad_id),
                    "name": entry.get("OBJECT_NAME", f"UNKNOWN-{norad_id}"),
                    "object_type": _map_object_type(entry.get("OBJECT_TYPE")),
                    "rcs_size": _map_rcs_size(entry.get("RCS_SIZE")),
                    "country_code": entry.get("COUNTRY_CODE"),
                    "launch_date": _parse_date(entry.get("LAUNCH_DATE")),
                    "decay_date": _parse_date(entry.get("DECAY_DATE")),
                    "tle_line1": tle_line1,
                    "tle_line2": entry.get("TLE_LINE2", ""),
                    "tle_epoch": _parse_tle_epoch(tle_line1) if tle_line1 else None,
                    "data_source": source,
                })

            if not values:
                continue

            stmt = pg_insert(SpaceObject).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["norad_id"],
                set_={
                    "name": stmt.excluded.name,
                    "object_type": stmt.excluded.object_type,
                    "rcs_size": stmt.excluded.rcs_size,
                    "country_code": stmt.excluded.country_code,
                    "launch_date": stmt.excluded.launch_date,
                    "decay_date": stmt.excluded.decay_date,
                    "tle_line1": stmt.excluded.tle_line1,
                    "tle_line2": stmt.excluded.tle_line2,
                    "tle_epoch": stmt.excluded.tle_epoch,
                    "data_source": stmt.excluded.data_source,
                    "updated_at": text("NOW()"),
                },
            )
            await session.execute(stmt)
            count += len(values)

            progress = min(100.0, (i + len(batch)) / len(catalog) * 80.0)
            await set_pipeline_status("ingestion", progress)

        await session.commit()
        logger.info(f"Upserted {count} objects from GP catalog")
        return count


async def _upsert_objects_from_tle(tle_text: str) -> int:
    """Fallback: upsert objects from raw TLE text (no metadata).

    Used when the GP JSON endpoint is unavailable. Objects created this
    way have no RCS size, country code, or launch date — only the
    minimal data needed for propagation (name, NORAD ID, TLE lines, epoch).
    """
    parsed = parse_tle_text(tle_text)
    if not parsed:
        return 0

    async with AsyncSessionLocal() as session:
        values = [
            {
                "norad_id": tle.norad_id,
                "name": tle.name or f"UNKNOWN-{tle.norad_id}",
                "object_type": ObjectType.DEBRIS,
                "tle_line1": tle.line1,
                "tle_line2": tle.line2,
                "tle_epoch": tle.epoch,
            }
            for tle in parsed
        ]

        stmt = pg_insert(SpaceObject).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["norad_id"],
            set_={
                "name": stmt.excluded.name,
                "tle_line1": stmt.excluded.tle_line1,
                "tle_line2": stmt.excluded.tle_line2,
                "tle_epoch": stmt.excluded.tle_epoch,
                "updated_at": text("NOW()"),
            },
        )
        await session.execute(stmt)
        await session.commit()

        logger.info(f"Upserted {len(values)} objects from TLE text (fallback mode)")
        return len(values)


async def _seed_profiles() -> int:
    """Seed satellite profiles for key satellites.

    Only inserts profiles that don't already exist (ON CONFLICT DO NOTHING).
    This allows operator profiles to be manually updated without being
    overwritten on each pipeline run.

    Returns count of new profiles seeded.
    """
    async with AsyncSessionLocal() as session:
        seeded = 0
        for profile_data in SEED_PROFILES:
            # Check if the satellite exists in the catalog first
            result = await session.execute(
                text("SELECT norad_id FROM objects WHERE norad_id = :nid"),
                {"nid": profile_data["norad_id"]},
            )
            if result.fetchone() is None:
                logger.debug(
                    f"Skipping profile seed for NORAD {profile_data['norad_id']} "
                    f"— not in catalog"
                )
                continue

            stmt = pg_insert(SatelliteProfile).values(**profile_data)
            stmt = stmt.on_conflict_do_nothing(index_elements=["norad_id"])
            result = await session.execute(stmt)
            if result.rowcount > 0:
                seeded += 1

        await session.commit()
        if seeded > 0:
            logger.info(f"Seeded {seeded} new satellite profiles")
        return seeded


async def _try_spacetrack_supplemental(celestrak_count: int) -> int:
    """Attempt to fetch supplemental objects from Space-Track.org.

    Only runs if Space-Track credentials are configured. Adds objects
    that aren't already in the database from CelesTrak.
    Non-fatal — any error is logged and returns 0.

    Args:
        celestrak_count: Number of objects already ingested from CelesTrak.
                         Used for progress reporting.

    Returns:
        Count of additional objects ingested from Space-Track.
    """
    settings = get_settings()
    if not settings.spacetrack_user or not settings.spacetrack_password:
        logger.debug("Space-Track credentials not configured — skipping supplemental ingestion")
        return 0

    try:
        from ingestion.spacetrack_client import fetch_spacetrack_gp_catalog, SpaceTrackError

        await set_pipeline_status("ingestion_spacetrack", 10.0)
        logger.info("Fetching supplemental data from Space-Track.org...")

        st_catalog = await fetch_spacetrack_gp_catalog(epoch_days=30)
        if not st_catalog:
            logger.info("Space-Track returned 0 objects — nothing to supplement")
            return 0

        await set_pipeline_status("ingestion_spacetrack", 50.0)
        st_count = await _upsert_objects_from_gp(st_catalog)

        await set_pipeline_status("ingestion_spacetrack", 100.0)
        logger.info(
            f"Space-Track supplemental ingestion: {st_count} objects "
            f"(total catalog now: {celestrak_count + st_count})"
        )
        return st_count

    except Exception as e:
        logger.warning(f"Space-Track supplemental ingestion failed (non-fatal): {e}")
        return 0


async def run_ingestion() -> int:
    """Execute the full ingestion pipeline.

    Pipeline stages:
      1. Report status: 'ingestion' at 0%
      2. Fetch GP catalog from CelesTrak (primary source)
      3. If GP fails, fall back to raw TLE text
      4. Upsert objects into database
      5. Optionally fetch supplemental data from Space-Track.org
      6. Seed operator profiles for key satellites
      7. Report status: 'ingestion' at 100%

    Data source hierarchy:
      - CelesTrak: Always tried first (free, no auth, ~25k active objects)
      - Space-Track: Tried second if credentials are configured (~50k objects)

    Returns:
        Total count of objects ingested from all sources (0 if all
        sources are unreachable and no fallback data is available).
    """
    await set_pipeline_status("ingestion", 0.0)
    logger.info("Starting ingestion pipeline...")

    count = 0

    # Source 1: CelesTrak GP catalog JSON (primary — free, no auth)
    try:
        catalog = await fetch_gp_catalog()
        count = await _upsert_objects_from_gp(catalog)
        logger.info(f"CelesTrak primary ingestion: {count} objects")
    except CelesTrakError as e:
        logger.warning(f"GP catalog fetch failed: {e} — trying TLE text fallback")

        # Fallback: Raw TLE text (no metadata)
        try:
            tle_text = await fetch_tle_data("active")
            count = await _upsert_objects_from_tle(tle_text)
        except CelesTrakError as e2:
            logger.error(
                f"Both GP catalog and TLE text fetch failed. "
                f"GP error: {e}, TLE error: {e2}. "
                f"Pipeline will use existing database data."
            )

    # Source 2: Space-Track.org (supplemental — optional, needs free account)
    st_count = await _try_spacetrack_supplemental(count)
    total_count = count + st_count

    # Seed profiles regardless of fetch success — they reference existing objects
    try:
        await _seed_profiles()
    except Exception as e:
        logger.error(f"Profile seeding failed: {e}", exc_info=True)

    await set_pipeline_status("ingestion", 100.0)
    logger.info(
        f"Ingestion pipeline complete: {total_count} objects "
        f"(CelesTrak: {count}, Space-Track: {st_count})"
    )
    return total_count
