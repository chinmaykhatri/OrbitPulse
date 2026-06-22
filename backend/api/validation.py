"""API endpoints for SOCRATES validation and system health."""
import logging

from fastapi import APIRouter

from core.socrates import validate_against_socrates
from schemas.conjunctions import SOCRATESValidation

logger = logging.getLogger("orbitpulse.api.validation")
router = APIRouter(prefix="/api", tags=["Validation"])


@router.get("/socrates", response_model=SOCRATESValidation)
async def get_socrates_validation():
    """Cross-validate OrbitPulse predictions against SOCRATES.

    Fetches the latest SOCRATES CSV from CelesTrak, matches against
    our conjunction database, and returns a comparison report.

    This endpoint makes a live HTTP request to CelesTrak, so response
    time depends on CelesTrak availability (typically 1-3 seconds).
    Results are not cached — each call fetches fresh data.
    """
    return await validate_against_socrates()


@router.get("/pipeline/status")
async def get_pipeline_status():
    """Detailed pipeline status for all stages.

    Returns the current stage (ingestion/propagation/detection) and
    progress percentage for frontend loading display.
    """
    from cache.position_cache import get_pipeline_status
    from core.engine import orbital_engine

    status = None
    try:
        status = await get_pipeline_status()
    except Exception as e:
        logger.error(f"Failed to get pipeline status: {e}")

    return {
        "pipeline": status,
        "catalog_size": orbital_engine.catalog_size,
        "is_propagated": orbital_engine.is_propagated,
    }
