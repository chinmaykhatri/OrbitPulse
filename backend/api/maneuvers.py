"""API endpoints for maneuver planning, approval, and negotiation."""
import logging

from fastapi import APIRouter, Path, HTTPException

from core.maneuver_planner import generate_maneuver_candidates
from core.negotiation import run_negotiation
from schemas.maneuvers import TradeOffMatrix
from schemas.negotiations import NegotiationContract

logger = logging.getLogger("orbitpulse.api.maneuvers")
router = APIRouter(prefix="/api", tags=["Maneuvers"])


@router.post("/maneuvers/{conjunction_id}", response_model=TradeOffMatrix)
async def plan_maneuvers(
    conjunction_id: int = Path(..., ge=1),
):
    """Generate maneuver candidates for a conjunction.

    Computes Tsiolkovsky fuel costs, simulates burn outcomes, and ranks
    candidates by trade-off efficiency (miss distance / fuel cost).
    Returns the trade-off matrix with AI recommendation.

    Requires X-Demo-Key header (POST endpoint).
    """
    matrix = await generate_maneuver_candidates(conjunction_id)
    if matrix is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Cannot plan maneuvers for conjunction {conjunction_id}. "
                f"Either the conjunction does not exist or no satellite has "
                f"an operator profile (not maneuverable)."
            ),
        )
    return matrix


@router.post("/negotiate/{conjunction_id}", response_model=NegotiationContract)
async def negotiate_conjunction(
    conjunction_id: int = Path(..., ge=1),
):
    """Run the negotiation protocol for a both-maneuverable conjunction.

    Executes the game-theoretic utility analysis, generates negotiation
    rounds, and produces a signed contract with SHA-256 hash.

    Only applicable when both objects have satellite profiles.
    Requires X-Demo-Key header (POST endpoint).
    """
    contract = await run_negotiation(conjunction_id)
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Cannot negotiate conjunction {conjunction_id}. "
                f"Either the conjunction does not exist or fewer than "
                f"2 satellites have operator profiles."
            ),
        )
    return contract
