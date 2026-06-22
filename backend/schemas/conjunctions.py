"""Schema models for conjunction data, triage funnel, risk timeline, and SOCRATES validation."""
from datetime import datetime

from pydantic import BaseModel


class ConjunctionBase(BaseModel):
    """Core conjunction data returned in list and detail endpoints."""
    id: int
    obj_a_id: int
    obj_b_id: int
    obj_a_name: str | None = None
    obj_b_name: str | None = None
    tca_time: datetime
    miss_distance_km: float
    prev_miss_distance_km: float | None
    relative_velocity_kms: float
    risk_score: float
    tier: str
    dismiss_reason: str | None
    both_maneuverable: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConjunctionDetail(ConjunctionBase):
    """Extended conjunction data including object type and size metadata."""
    obj_a_type: str | None = None
    obj_b_type: str | None = None
    obj_a_rcs: str | None = None
    obj_b_rcs: str | None = None


class FunnelStats(BaseModel):
    """Triage funnel statistics — the three-tier count display.

    total_screened is the denominator (all conjunctions detected this cycle).
    watchlist and action_required are the tier counts.
    """
    total_screened: int
    watchlist: int
    action_required: int
    last_updated: datetime | None


class TimelineEvent(BaseModel):
    """Single event in the 72h risk timeline for a satellite.

    The timeline is sorted by tca_time ascending and colored by tier
    in the frontend's Recharts BarChart component.
    """
    tca_time: datetime
    risk_score: float
    tier: str
    obj_b_name: str
    miss_distance_km: float
    relative_velocity_kms: float

    model_config = {"from_attributes": True}


class SOCRATESMatch(BaseModel):
    """Comparison between our prediction and SOCRATES for the same conjunction pair."""
    our_prediction: dict
    socrates_prediction: dict
    delta_km: float
    norad_ids: list[int]


class SOCRATESValidation(BaseModel):
    """Full SOCRATES validation result set with match list and fetch timestamp."""
    matches: list[SOCRATESMatch]
    last_fetched: datetime | None
