"""Schema models for the fragmentation (Kessler syndrome) simulation."""
from pydantic import BaseModel, Field


class FragmentationRequest(BaseModel):
    """Request to trigger a simulated breakup event.

    fragment_count is clamped to max_fragment_count from config.
    """
    fragment_count: int = Field(default=50, ge=1, le=200)


class FragmentationResponse(BaseModel):
    """Result of a successful fragmentation simulation trigger."""
    fragments_generated: int
    synthetic_ids: list[int]
    parent_norad_id: int


class FragmentationCleanupResponse(BaseModel):
    """Result of cleaning up expired or all fragment data."""
    fragments_removed: int
