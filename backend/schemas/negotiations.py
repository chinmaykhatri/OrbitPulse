"""Schema models for the agent-to-agent negotiation protocol."""
from pydantic import BaseModel


class NegotiationRound(BaseModel):
    """Single round in the negotiation protocol.

    Each round has a proposer (operator NORAD ID or 0 for system),
    a proposal (which satellite maneuvers and with what burn),
    and a response from the other party (accept/counter/reject with reasoning).
    """
    round: int
    proposer: str
    proposal: str | None = None
    response: str | None = None
    reasoning: str | None = None


class NegotiationOutcome(BaseModel):
    """Final result of the negotiation protocol.

    The maneuvering_satellite field indicates which operator agreed to burn.
    contract_hash is a SHA-256 hash of the agreement terms for audit trail.
    fallback_used indicates whether the Claude API was unavailable and the
    deterministic objective function was used instead.
    """
    maneuvering_satellite: int
    burn: dict
    contract_hash: str
    fallback_used: bool
    summary: str


class NegotiationContract(BaseModel):
    """Complete negotiation record — all rounds plus the final outcome."""
    conjunction_id: int
    rounds: list[NegotiationRound]
    outcome: NegotiationOutcome
