"""API endpoints for conjunction data, triage funnel, and risk timeline."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Path, HTTPException
from sqlalchemy import select, func, desc

from db.session import AsyncSessionLocal
from db.models import Conjunction, SpaceObject, TriageTier
from schemas.conjunctions import ConjunctionBase, ConjunctionDetail, FunnelStats, TimelineEvent

logger = logging.getLogger("orbitpulse.api.conjunctions")
router = APIRouter(prefix="/api", tags=["Conjunctions"])


@router.get("/conjunctions", response_model=list[ConjunctionBase])
async def list_conjunctions(
    tier: str | None = Query(default=None, description="Filter by tier: ACTION, WATCHLIST, DISMISSED"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List detected conjunctions, optionally filtered by triage tier.

    Results are ordered by TCA time descending (most imminent first).
    Each conjunction includes both object names resolved from the catalog.
    """
    async with AsyncSessionLocal() as session:
        # Base query with object name joins
        obj_a = select(SpaceObject.name).where(
            SpaceObject.norad_id == Conjunction.obj_a_id
        ).correlate(Conjunction).scalar_subquery()
        obj_b = select(SpaceObject.name).where(
            SpaceObject.norad_id == Conjunction.obj_b_id
        ).correlate(Conjunction).scalar_subquery()

        query = select(Conjunction).order_by(desc(Conjunction.tca_time))

        if tier:
            try:
                tier_enum = TriageTier(tier.upper())
                query = query.where(Conjunction.tier == tier_enum)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid tier '{tier}'. Must be one of: ACTION, WATCHLIST, DISMISSED",
                )

        query = query.offset(offset).limit(limit)
        result = await session.execute(query)
        conjunctions = result.scalars().all()

        # Resolve object names in a second pass to avoid complex join
        norad_ids = set()
        for c in conjunctions:
            norad_ids.add(c.obj_a_id)
            norad_ids.add(c.obj_b_id)

        name_result = await session.execute(
            select(SpaceObject.norad_id, SpaceObject.name).where(
                SpaceObject.norad_id.in_(norad_ids)
            )
        )
        name_map = {row.norad_id: row.name for row in name_result.all()}

    return [
        ConjunctionBase(
            id=c.id,
            obj_a_id=c.obj_a_id,
            obj_b_id=c.obj_b_id,
            obj_a_name=name_map.get(c.obj_a_id),
            obj_b_name=name_map.get(c.obj_b_id),
            tca_time=c.tca_time,
            miss_distance_km=c.miss_distance_km,
            prev_miss_distance_km=c.prev_miss_distance_km,
            relative_velocity_kms=c.relative_velocity_kms,
            risk_score=c.risk_score,
            tier=c.tier.value,
            dismiss_reason=c.dismiss_reason,
            both_maneuverable=c.both_maneuverable,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in conjunctions
    ]


@router.get("/conjunctions/{conjunction_id}", response_model=ConjunctionDetail)
async def get_conjunction_detail(
    conjunction_id: int = Path(..., ge=1),
):
    """Get full detail for a single conjunction including object metadata."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Conjunction).where(Conjunction.id == conjunction_id)
        )
        conj = result.scalar_one_or_none()

        if conj is None:
            raise HTTPException(status_code=404, detail=f"Conjunction {conjunction_id} not found")

        # Fetch both objects' metadata
        obj_result = await session.execute(
            select(SpaceObject).where(
                SpaceObject.norad_id.in_([conj.obj_a_id, conj.obj_b_id])
            )
        )
        objects = {obj.norad_id: obj for obj in obj_result.scalars().all()}
        obj_a = objects.get(conj.obj_a_id)
        obj_b = objects.get(conj.obj_b_id)

    return ConjunctionDetail(
        id=conj.id,
        obj_a_id=conj.obj_a_id,
        obj_b_id=conj.obj_b_id,
        obj_a_name=obj_a.name if obj_a else None,
        obj_b_name=obj_b.name if obj_b else None,
        obj_a_type=obj_a.object_type.value if obj_a and obj_a.object_type else None,
        obj_b_type=obj_b.object_type.value if obj_b and obj_b.object_type else None,
        obj_a_rcs=obj_a.rcs_size.value if obj_a and obj_a.rcs_size else None,
        obj_b_rcs=obj_b.rcs_size.value if obj_b and obj_b.rcs_size else None,
        tca_time=conj.tca_time,
        miss_distance_km=conj.miss_distance_km,
        prev_miss_distance_km=conj.prev_miss_distance_km,
        relative_velocity_kms=conj.relative_velocity_kms,
        risk_score=conj.risk_score,
        tier=conj.tier.value,
        dismiss_reason=conj.dismiss_reason,
        both_maneuverable=conj.both_maneuverable,
        created_at=conj.created_at,
        updated_at=conj.updated_at,
    )


@router.get("/funnel", response_model=FunnelStats)
async def get_funnel_stats():
    """Triage funnel statistics — counts per tier.

    Returns total_screened (all conjunctions), watchlist count,
    and action_required count. Used by the frontend funnel visualization.
    """
    async with AsyncSessionLocal() as session:
        total = await session.execute(select(func.count(Conjunction.id)))
        action = await session.execute(
            select(func.count(Conjunction.id)).where(Conjunction.tier == TriageTier.ACTION)
        )
        watchlist = await session.execute(
            select(func.count(Conjunction.id)).where(Conjunction.tier == TriageTier.WATCHLIST)
        )
        last_updated_result = await session.execute(
            select(func.max(Conjunction.updated_at))
        )

    return FunnelStats(
        total_screened=total.scalar_one() or 0,
        watchlist=watchlist.scalar_one() or 0,
        action_required=action.scalar_one() or 0,
        last_updated=last_updated_result.scalar_one(),
    )


@router.get("/timeline/{norad_id}", response_model=list[TimelineEvent])
async def get_risk_timeline(
    norad_id: int = Path(..., ge=1),
):
    """72-hour risk timeline for a specific satellite.

    Returns all conjunctions where this satellite is either object A or
    object B, sorted by TCA time ascending. The frontend renders this
    as a bar chart colored by tier.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Conjunction).where(
                (Conjunction.obj_a_id == norad_id) | (Conjunction.obj_b_id == norad_id)
            ).order_by(Conjunction.tca_time)
        )
        conjunctions = result.scalars().all()

        if not conjunctions:
            return []

        # Resolve the "other" object's name for each conjunction
        other_ids = set()
        for c in conjunctions:
            other_id = c.obj_b_id if c.obj_a_id == norad_id else c.obj_a_id
            other_ids.add(other_id)

        name_result = await session.execute(
            select(SpaceObject.norad_id, SpaceObject.name).where(
                SpaceObject.norad_id.in_(other_ids)
            )
        )
        name_map = {row.norad_id: row.name for row in name_result.all()}

    return [
        TimelineEvent(
            tca_time=c.tca_time,
            risk_score=c.risk_score,
            tier=c.tier.value,
            obj_b_name=name_map.get(
                c.obj_b_id if c.obj_a_id == norad_id else c.obj_a_id,
                "UNKNOWN"
            ),
            miss_distance_km=c.miss_distance_km,
            relative_velocity_kms=c.relative_velocity_kms,
        )
        for c in conjunctions
    ]
