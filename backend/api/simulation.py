"""API endpoints for fragmentation simulation and cleanup."""
import logging

from fastapi import APIRouter, Path, HTTPException

from core.fragmentation import simulate_fragmentation, cleanup_fragments
from cache.position_cache import is_simulation_locked
from schemas.simulation import FragmentationRequest, FragmentationResponse, FragmentationCleanupResponse

logger = logging.getLogger("orbitpulse.api.simulation")
router = APIRouter(prefix="/api", tags=["Simulation"])


@router.post(
    "/simulate/fragment/{norad_id}",
    response_model=FragmentationResponse,
)
async def trigger_fragmentation(
    norad_id: int = Path(..., ge=1),
    request: FragmentationRequest = FragmentationRequest(),
):
    """Simulate a satellite breakup event (Kessler syndrome visualization).

    Generates fragment objects with NASA breakup model velocity distributions.
    Fragments appear on the globe and expire after the configured lifetime.

    Only one simulation can run at a time (protected by Redis lock).
    Returns 429 if another simulation is in progress.

    Requires X-Demo-Key header (POST endpoint).
    """
    if await is_simulation_locked():
        raise HTTPException(
            status_code=429,
            detail="Another fragmentation simulation is currently running. Please wait.",
        )

    result = await simulate_fragmentation(norad_id, request.fragment_count)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Cannot fragment NORAD {norad_id}. "
                f"Satellite not found or missing TLE data."
            ),
        )

    return FragmentationResponse(**result)


@router.delete(
    "/simulate/fragment/{norad_id}",
    response_model=FragmentationCleanupResponse,
)
async def cleanup_fragmentation(
    norad_id: int = Path(..., ge=1),
):
    """Clean up fragment data for a specific parent satellite.

    Removes all fragments spawned by this satellite from both the
    database and Redis position cache.

    Requires X-Demo-Key header (DELETE endpoint).
    """
    removed = await cleanup_fragments(norad_id)
    return FragmentationCleanupResponse(fragments_removed=removed)


@router.delete(
    "/simulate/fragments/expired",
    response_model=FragmentationCleanupResponse,
)
async def cleanup_expired_fragments():
    """Clean up all expired fragment data.

    Removes fragments past their expiry time from both the database
    and Redis position cache. Called automatically by the scheduled
    cleanup task, but can also be triggered manually.

    Requires X-Demo-Key header (DELETE endpoint).
    """
    removed = await cleanup_fragments()
    return FragmentationCleanupResponse(fragments_removed=removed)
