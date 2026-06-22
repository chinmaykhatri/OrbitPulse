"""Schema package — re-exports all schema models for convenient imports."""
from schemas.common import ErrorResponse, HealthResponse
from schemas.objects import CatalogObject, ISSPosition, PositionUpdate
from schemas.conjunctions import (
    ConjunctionBase,
    ConjunctionDetail,
    FunnelStats,
    TimelineEvent,
    SOCRATESMatch,
    SOCRATESValidation,
)
from schemas.maneuvers import (
    ManeuverCandidate,
    Recommendation,
    TradeOffMatrix,
    ManeuverApprovalResponse,
    MissionLifeImpact,
)
from schemas.negotiations import NegotiationRound, NegotiationOutcome, NegotiationContract
from schemas.simulation import (
    FragmentationRequest,
    FragmentationResponse,
    FragmentationCleanupResponse,
)

__all__ = [
    "ErrorResponse",
    "HealthResponse",
    "CatalogObject",
    "ISSPosition",
    "PositionUpdate",
    "ConjunctionBase",
    "ConjunctionDetail",
    "FunnelStats",
    "TimelineEvent",
    "SOCRATESMatch",
    "SOCRATESValidation",
    "ManeuverCandidate",
    "Recommendation",
    "TradeOffMatrix",
    "ManeuverApprovalResponse",
    "MissionLifeImpact",
    "NegotiationRound",
    "NegotiationOutcome",
    "NegotiationContract",
    "FragmentationRequest",
    "FragmentationResponse",
    "FragmentationCleanupResponse",
]
