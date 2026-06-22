"""Shared response models used across multiple endpoints."""
from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response envelope — every error uses this format."""
    error: str
    detail: str
    code: str


class HealthResponse(BaseModel):
    """Health check response with pipeline readiness status."""
    status: str
    ready: bool
    objects_loaded: int
    stage: str | None = None
    progress_pct: float | None = None
