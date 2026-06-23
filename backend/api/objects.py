"""API endpoints for space objects, ISS tracking, and positions."""
import logging

from fastapi import APIRouter, Query

from core.engine import orbital_engine
from schemas.objects import CatalogObject, ISSPosition

logger = logging.getLogger("orbitpulse.api.objects")
router = APIRouter(prefix="/api", tags=["Objects"])


@router.get("/objects", response_model=list[CatalogObject])
async def list_objects(
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    object_type: str | None = Query(default=None),
):
    """List satellite catalog entries with optional type filtering.

    Returns basic metadata (no positions) for catalog browsing.
    For positions, use the /api/positions endpoint or WebSocket.
    """
    from sqlalchemy import select
    from db.session import AsyncSessionLocal
    from db.models import SpaceObject

    async with AsyncSessionLocal() as session:
        query = select(SpaceObject).offset(offset).limit(limit)
        if object_type:
            query = query.where(SpaceObject.object_type == object_type)
        result = await session.execute(query)
        objects = result.scalars().all()

    return [
        CatalogObject(
            norad_id=obj.norad_id,
            name=obj.name,
            object_type=str(obj.object_type.value) if obj.object_type else "DEBRIS",
            rcs_size=str(obj.rcs_size.value) if obj.rcs_size else None,
            country_code=obj.country_code,
        )
        for obj in objects
    ]


@router.get("/iss")
async def get_iss_position():
    """Real-time ISS position with self-validation.

    Returns latitude, longitude, altitude, and a validated flag that
    indicates whether the SGP4-computed altitude falls within the
    expected ISS range (380-440 km). This is a self-consistency check
    that helps detect expired TLE data.

    Cross-check: compare with https://www.n2yo.com/?s=25544
    """
    position = await orbital_engine.get_iss_position()
    if position is None:
        return {"error": "iss_unavailable", "detail": "ISS position not available — TLE may be missing or expired"}
    return position


@router.get("/positions")
async def get_positions(
    limit: int = Query(default=5000, ge=1, le=25000),
):
    """Current positions for up to 25,000 objects in flat array format.

    Returns: [[norad_id, lat, lon, alt_km], ...]

    This endpoint is primarily for initial data load. Ongoing updates
    come via the WebSocket at /ws/live.
    """
    positions = await orbital_engine.get_current_positions_batch(limit=limit)
    return {"positions": positions, "count": len(positions)}


@router.get("/sources")
async def get_data_sources():
    """Data source statistics — shows object counts per ingestion source.

    Returns a breakdown of objects by data_source (celestrak, space-track)
    with the most recent TLE epoch for each source. Useful for verifying
    that the dual-source pipeline is working correctly.
    """
    from sqlalchemy import select, func
    from db.session import AsyncSessionLocal
    from db.models import SpaceObject

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                SpaceObject.data_source,
                func.count(SpaceObject.norad_id).label("count"),
                func.max(SpaceObject.tle_epoch).label("latest_epoch"),
                func.min(SpaceObject.tle_epoch).label("oldest_epoch"),
            ).group_by(SpaceObject.data_source)
        )
        rows = result.all()

    sources = []
    total = 0
    for row in rows:
        count = row.count
        total += count
        sources.append({
            "source": row.data_source,
            "objects": count,
            "latest_epoch": row.latest_epoch.isoformat() if row.latest_epoch else None,
            "oldest_epoch": row.oldest_epoch.isoformat() if row.oldest_epoch else None,
        })

    return {
        "sources": sources,
        "total_objects": total,
        "primary": "celestrak",
        "supplemental": "space-track",
        "note": "Space-Track.org requires a free account (SPACETRACK_USER/SPACETRACK_PASSWORD env vars). CelesTrak is always available without authentication.",
    }
