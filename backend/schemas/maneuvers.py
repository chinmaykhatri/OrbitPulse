"""Schema models for maneuver planning, trade-off matrix, and burn approval."""
from datetime import datetime

from pydantic import BaseModel


class MissionLifeImpact(BaseModel):
    """Fuel cost expressed as mission lifetime reduction."""
    days: float
    pct_of_remaining: float


class ManeuverCandidate(BaseModel):
    """Single maneuver option in the trade-off matrix.

    Each candidate represents one possible burn (direction × delta-v magnitude).
    The new_miss_distance_km is computed by re-propagating the modified orbit
    and re-running fine screening against the other object.
    secondary_conjunctions is the count of NEW close approaches introduced
    by the orbit change (scoped re-screening against altitude band neighbors).
    """
    id: int
    direction: str
    delta_v_ms: float
    burn_time: datetime
    new_miss_distance_km: float
    fuel_cost_kg: float
    mission_life_impact: MissionLifeImpact
    secondary_conjunctions: int
    status: str
    rejection_reason: str | None

    model_config = {"from_attributes": True}


class Recommendation(BaseModel):
    """AI-generated or template-based maneuver recommendation.

    source is "claude" when the Claude API is available, "template" when
    using the deterministic fallback. The reasoning field contains the
    natural language explanation of the choice.
    """
    chosen_id: int | None
    reasoning: str
    source: str


class TradeOffMatrix(BaseModel):
    """Complete maneuver analysis for a conjunction.

    Contains the conjunction context, all candidate burns, and the
    AI recommendation. This is the main payload for the frontend's
    trade-off matrix component.
    """
    conjunction: dict
    candidates: list[ManeuverCandidate]
    recommendation: Recommendation


class ManeuverApprovalResponse(BaseModel):
    """Response after operator approves a specific maneuver.

    Includes the post-burn orbit preview (new_orbit_path) for the
    frontend to redraw the satellite's ground track on the globe.
    """
    approved: bool
    maneuver_id: int
    satellite_norad_id: int
    new_orbit_path: list[list[float]]
    burn_executed_at: datetime
    new_miss_distance_km: float
    alert_status: str
