"""API endpoints for data export — CDM (Conjunction Data Message) format."""
import logging

from fastapi import APIRouter, Path, HTTPException
from fastapi.responses import PlainTextResponse

from core.cdm_generator import generate_cdm

logger = logging.getLogger("orbitpulse.api.export")
router = APIRouter(prefix="/api", tags=["Export"])


@router.get(
    "/conjunctions/{conjunction_id}/cdm",
    response_class=PlainTextResponse,
    responses={
        200: {
            "content": {"text/plain": {}},
            "description": "CCSDS 508.0-B-1 Conjunction Data Message in KVN format",
        },
    },
)
async def export_cdm(
    conjunction_id: int = Path(..., ge=1),
):
    """Export conjunction as a CCSDS-standard Conjunction Data Message.

    Returns the CDM in Key-Value Notation (KVN) text format, the
    international standard used by NASA, ESA, JAXA, and every space
    agency for sharing conjunction assessments.

    The response is a plain text file that can be directly ingested by
    operational conjunction assessment systems.

    Content-Type: text/plain
    """
    cdm_text = await generate_cdm(conjunction_id)
    if cdm_text is None:
        raise HTTPException(
            status_code=404,
            detail=f"Conjunction {conjunction_id} not found",
        )

    return PlainTextResponse(
        content=cdm_text,
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=OP-CDM-{conjunction_id:06d}.kvn",
        },
    )
