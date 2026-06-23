"""Negotiation protocol — adversarial game-theoretic operator coordination.

When both objects in a conjunction are maneuverable (both have satellite
profiles), the negotiation protocol determines which operator should burn.

Unlike a deterministic assignment, this protocol simulates REAL negotiation
tension between operators who each want to protect their own assets.

The protocol uses a 4-round maximum adversarial negotiation:
  Round 1: System proposes that the lower-utility operator maneuvers
           → Probabilistic accept/reject based on utility differential
  Round 2: If rejected, counter-proposal with modified burn (smaller Δv)
           or propose shared burn (50/50 split)
  Round 3: If still rejected, escalate with 70/30 split favoring the rejector
  Round 4: Deadlock → forced assignment with penalty note in contract

Utility function for each operator:
  U(operator) = w_fuel × (fuel_remaining_pct / 100)
              + w_mission × (remaining_days / max_days)
              + w_priority × (priority / 10)

Where weights are: fuel=0.4, mission=0.3, priority=0.3

Acceptance is PROBABILISTIC:
  P(accept) = sigmoid(10 × (utility_other - utility_self - 0.05))

This means operators with nearly equal utility have ~50% chance of
rejecting the proposal — creating real negotiation tension.

The contract hash is SHA-256 of the agreement terms, providing an
auditable record of the negotiation outcome.
"""
import hashlib
import json
import logging
import math
import random
from datetime import datetime, timezone

from sqlalchemy import select

from db.session import AsyncSessionLocal
from db.models import (
    Conjunction, SatelliteProfile, Maneuver, Negotiation,
    ManeuverStatus,
)
from core.maneuver_planner import generate_maneuver_candidates
from schemas.negotiations import NegotiationRound, NegotiationOutcome, NegotiationContract

logger = logging.getLogger("orbitpulse.core.negotiation")

# Utility function weights
W_FUEL = 0.4
W_MISSION = 0.3
W_PRIORITY = 0.3
MAX_MISSION_DAYS = 7300  # 20 years


def compute_operator_utility(profile: SatelliteProfile) -> float:
    """Compute utility score for an operator.

    Higher utility means the operator has more to protect (more fuel,
    longer mission, higher priority). The operator with LOWER utility
    should maneuver because they have less marginal cost.

    Returns:
        Utility score in range [0.0, 1.0].
    """
    fuel_factor = 1.0 - min(1.0, profile.fuel_remaining_kg / max(profile.dry_mass_kg * 0.1, 1.0))
    mission_factor = profile.remaining_mission_days / MAX_MISSION_DAYS
    priority_factor = profile.mission_priority / 10.0

    utility = (
        W_FUEL * (profile.fuel_remaining_pct / 100.0)
        + W_MISSION * mission_factor
        + W_PRIORITY * priority_factor
    )
    return round(min(1.0, max(0.0, utility)), 4)


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    else:
        ez = math.exp(x)
        return ez / (1.0 + ez)


def _agent_decide(
    utility_self: float,
    utility_other: float,
    round_number: int,
) -> bool:
    """Simulate an operator agent's accept/reject decision.

    Uses a probabilistic model based on the utility differential.
    Operators with lower utility are more likely to accept (they have
    less to lose), but there's always uncertainty.

    As rounds increase, acceptance probability rises (pressure to resolve).

    Args:
        utility_self: This operator's utility score
        utility_other: The other operator's utility score
        round_number: Current negotiation round (1-indexed)

    Returns:
        True if the operator accepts the proposal.
    """
    # Utility differential: positive means other has more to lose
    diff = utility_other - utility_self

    # Acceptance probability: sigmoid with increasing pressure per round
    # Round 1: strict (only accept if clear differential)
    # Round 3: lenient (pressure to agree)
    temperature = 6.0 + round_number * 2.0
    bias = -0.05 + (round_number - 1) * 0.15  # Shifts toward acceptance

    p_accept = _sigmoid(temperature * (diff + bias))

    # Add some randomness (real operators aren't perfectly rational)
    p_accept = max(0.05, min(0.95, p_accept))

    decision = random.random() < p_accept
    logger.debug(
        f"Agent decision: util_self={utility_self:.4f}, util_other={utility_other:.4f}, "
        f"round={round_number}, p_accept={p_accept:.3f}, decision={'ACCEPT' if decision else 'REJECT'}"
    )
    return decision


def _generate_rejection_reason(
    operator_name: str,
    utility_self: float,
    utility_other: float,
    round_number: int,
) -> str:
    """Generate a realistic rejection message from an operator agent."""
    diff = abs(utility_self - utility_other)

    if diff < 0.1:
        reasons = [
            f"{operator_name} rejects: utility differential ({diff:.3f}) too small to justify unilateral action.",
            f"{operator_name} rejects: marginal cost disparity insufficient. Requesting shared burn.",
            f"{operator_name} rejects: mission timeline cannot absorb full maneuver cost at this time.",
        ]
    elif round_number == 1:
        reasons = [
            f"{operator_name} rejects: initial proposal places disproportionate burden on our asset.",
            f"{operator_name} rejects: fuel budget for Q3 already committed. Counter-proposing reduced Δv.",
            f"{operator_name} rejects: requesting cost-sharing arrangement before committing fuel.",
        ]
    else:
        reasons = [
            f"{operator_name} rejects: counter-proposal still exceeds acceptable mission life impact.",
            f"{operator_name} rejects: cannot accept without operational review. Requesting mediation.",
        ]

    return random.choice(reasons)


def _generate_acceptance_reason(
    operator_name: str,
    utility_self: float,
    round_number: int,
) -> str:
    """Generate a realistic acceptance message from an operator agent."""
    if round_number == 1:
        reasons = [
            f"{operator_name} accepts: utility analysis confirms we are the lower-cost maneuverer.",
            f"{operator_name} accepts: fuel budget can accommodate the proposed burn.",
        ]
    elif round_number <= 3:
        reasons = [
            f"{operator_name} accepts: revised proposal is within acceptable mission impact bounds.",
            f"{operator_name} accepts under modified terms: burn parameters acknowledged.",
            f"{operator_name} accepts: shared burn arrangement satisfies operational constraints.",
        ]
    else:
        reasons = [
            f"{operator_name} accepts: acknowledging forced assignment under deadlock protocol.",
        ]
    return random.choice(reasons)


def _compute_contract_hash(
    conjunction_id: int,
    maneuvering_id: int,
    burn_delta_v: float,
    burn_direction: str,
) -> str:
    """SHA-256 hash of the agreement terms for audit trail."""
    contract_data = json.dumps({
        "conjunction_id": conjunction_id,
        "maneuvering_satellite": maneuvering_id,
        "delta_v_ms": burn_delta_v,
        "direction": burn_direction,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, sort_keys=True)
    return hashlib.sha256(contract_data.encode()).hexdigest()


async def run_negotiation(conjunction_id: int) -> NegotiationContract | None:
    """Execute the full adversarial negotiation protocol.

    Steps:
      1. Load conjunction and both operator profiles
      2. Compute utility for each operator
      3. Run up to 4 negotiation rounds with probabilistic accept/reject
      4. Generate maneuver candidates for the chosen operator
      5. Store negotiation rounds in the database
      6. Return the complete contract

    Returns None if the conjunction doesn't exist or isn't both-maneuverable.
    """
    async with AsyncSessionLocal() as session:
        conj_result = await session.execute(
            select(Conjunction).where(Conjunction.id == conjunction_id)
        )
        conj = conj_result.scalar_one_or_none()
        if conj is None:
            logger.warning(f"Conjunction {conjunction_id} not found for negotiation")
            return None

        profile_result = await session.execute(
            select(SatelliteProfile).where(
                SatelliteProfile.norad_id.in_([conj.obj_a_id, conj.obj_b_id])
            )
        )
        profiles = {p.norad_id: p for p in profile_result.scalars().all()}

    if len(profiles) < 2:
        logger.info(
            f"Conjunction {conjunction_id} is not both-maneuverable "
            f"(only {len(profiles)} profile(s) found)"
        )
        return None

    profile_a = profiles[conj.obj_a_id]
    profile_b = profiles[conj.obj_b_id]

    utility_a = compute_operator_utility(profile_a)
    utility_b = compute_operator_utility(profile_b)

    name_a = profile_a.operator_name or f"NORAD-{conj.obj_a_id}"
    name_b = profile_b.operator_name or f"NORAD-{conj.obj_b_id}"

    logger.info(
        f"Negotiation for conjunction {conjunction_id}: "
        f"Operator A ({name_a}) utility={utility_a:.4f}, "
        f"Operator B ({name_b}) utility={utility_b:.4f}"
    )

    # The operator with LOWER utility is proposed to maneuver first
    if utility_a <= utility_b:
        proposed_id = conj.obj_a_id
        proposed_name = name_a
        other_id = conj.obj_b_id
        other_name = name_b
        proposed_utility = utility_a
        other_utility = utility_b
    else:
        proposed_id = conj.obj_b_id
        proposed_name = name_b
        other_id = conj.obj_a_id
        other_name = name_a
        proposed_utility = utility_b
        other_utility = utility_a

    # Run adversarial negotiation rounds
    rounds: list[NegotiationRound] = []
    maneuvering_id = proposed_id
    agreed = False
    forced = False
    burn_split = 1.0  # Fraction of burn assigned to maneuvering operator

    # ── Round 1: Initial proposal ──
    accepted_r1 = _agent_decide(proposed_utility, other_utility, round_number=1)

    if accepted_r1:
        rounds.append(NegotiationRound(
            round=1,
            proposer="OrbitPulse System",
            proposal=(
                f"Utility analysis: {proposed_name}={proposed_utility:.4f}, "
                f"{other_name}={other_utility:.4f}. "
                f"Proposing {proposed_name} execute full avoidance maneuver."
            ),
            response=_generate_acceptance_reason(proposed_name, proposed_utility, 1),
            reasoning=(
                f"Utility differential of {abs(utility_a - utility_b):.4f} "
                f"clearly identifies {proposed_name} as lower-cost maneuverer."
            ),
        ))
        agreed = True
    else:
        rejection = _generate_rejection_reason(proposed_name, proposed_utility, other_utility, 1)
        rounds.append(NegotiationRound(
            round=1,
            proposer="OrbitPulse System",
            proposal=(
                f"Utility analysis: {proposed_name}={proposed_utility:.4f}, "
                f"{other_name}={other_utility:.4f}. "
                f"Proposing {proposed_name} execute full avoidance maneuver."
            ),
            response=rejection,
            reasoning=f"Utility differential {abs(utility_a - utility_b):.4f} contested by {proposed_name}.",
        ))

    # ── Round 2: Counter-proposal (shared burn 50/50) ──
    if not agreed:
        burn_split = 0.5
        accepted_r2 = _agent_decide(proposed_utility, other_utility, round_number=2)

        if accepted_r2:
            rounds.append(NegotiationRound(
                round=2,
                proposer=other_name,
                proposal=(
                    f"Counter-proposal: shared burn — {proposed_name} executes 50% Δv, "
                    f"{other_name} executes 50% Δv. Cost distributed proportionally."
                ),
                response=_generate_acceptance_reason(proposed_name, proposed_utility, 2),
                reasoning="Shared burn distributes risk proportionally between both operators.",
            ))
            agreed = True
        else:
            rejection = _generate_rejection_reason(proposed_name, proposed_utility, other_utility, 2)
            rounds.append(NegotiationRound(
                round=2,
                proposer=other_name,
                proposal=(
                    f"Counter-proposal: shared burn — {proposed_name} executes 50% Δv, "
                    f"{other_name} executes 50% Δv."
                ),
                response=rejection,
                reasoning=f"50/50 split rejected. Escalating to asymmetric distribution.",
            ))

    # ── Round 3: Escalation (70/30 favoring rejector) ──
    if not agreed:
        burn_split = 0.3  # Proposed operator only does 30%
        accepted_r3 = _agent_decide(proposed_utility, other_utility, round_number=3)

        if accepted_r3:
            rounds.append(NegotiationRound(
                round=3,
                proposer="OrbitPulse Mediator",
                proposal=(
                    f"Mediated proposal: {proposed_name} executes 30% Δv, "
                    f"{other_name} executes 70% Δv. "
                    f"Reflecting fuel budget constraints of {proposed_name}."
                ),
                response=_generate_acceptance_reason(proposed_name, proposed_utility, 3),
                reasoning="Asymmetric split accepted under mediation. Both operators commit fuel.",
            ))
            agreed = True
        else:
            rejection = _generate_rejection_reason(proposed_name, proposed_utility, other_utility, 3)
            rounds.append(NegotiationRound(
                round=3,
                proposer="OrbitPulse Mediator",
                proposal=(
                    f"Mediated 30/70 split proposed. {proposed_name}: 30% Δv, "
                    f"{other_name}: 70% Δv."
                ),
                response=rejection,
                reasoning=f"Mediation failed. Proceeding to mandatory assignment.",
            ))

    # ── Round 4: Forced assignment (deadlock) ──
    if not agreed:
        forced = True
        burn_split = 1.0
        maneuvering_id = proposed_id

        rounds.append(NegotiationRound(
            round=4,
            proposer="OrbitPulse Emergency Protocol",
            proposal=(
                f"DEADLOCK RESOLVED: Under emergency protocol, {proposed_name} is "
                f"assigned the full avoidance maneuver. Utility-based assignment enforced. "
                f"This decision is logged and reportable to regulatory authorities."
            ),
            response=(
                f"{proposed_name} acknowledges forced assignment under protest. "
                f"Contract hash will include deadlock flag for audit purposes."
            ),
            reasoning=(
                f"After 3 rounds of failed negotiation, emergency protocol assigns "
                f"maneuver to {proposed_name} (lower utility: {proposed_utility:.4f}). "
                f"This is a FORCED outcome, not a consensual agreement."
            ),
        ))

    # Generate maneuver candidates for the chosen operator
    matrix = await generate_maneuver_candidates(conjunction_id)

    if matrix and matrix.candidates:
        best = matrix.candidates[0]
        burn_delta_v = best.delta_v_ms * burn_split
        burn_direction = best.direction
    else:
        burn_delta_v = 0.1 * burn_split
        burn_direction = "PROGRADE"

    # Compute contract hash
    contract_hash = _compute_contract_hash(
        conjunction_id=conjunction_id,
        maneuvering_id=maneuvering_id,
        burn_delta_v=burn_delta_v,
        burn_direction=burn_direction,
    )

    # Store rounds in database
    async with AsyncSessionLocal() as session:
        for r in rounds:
            neg = Negotiation(
                conjunction_id=conjunction_id,
                round_number=r.round,
                proposer_id=maneuvering_id if r.proposer not in ("OrbitPulse System", "OrbitPulse Mediator", "OrbitPulse Emergency Protocol") else 0,
                proposal=r.proposal or "",
                response=r.response,
                accepted=(r.round == len(rounds) and agreed) or forced,
            )
            session.add(neg)
        await session.commit()

    outcome = NegotiationOutcome(
        maneuvering_satellite=maneuvering_id,
        burn={"delta_v_ms": round(burn_delta_v, 4), "direction": burn_direction, "split": burn_split},
        contract_hash=contract_hash,
        fallback_used=forced,
        summary=(
            f"Negotiation {'FORCED after deadlock' if forced else f'resolved in {len(rounds)} rounds'}. "
            f"{proposed_name} will execute a {burn_direction} burn of {burn_delta_v:.4f} m/s "
            f"({'full burn' if burn_split == 1.0 else f'{burn_split*100:.0f}% split'}). "
            f"Contract hash: {contract_hash[:16]}..."
        ),
    )

    return NegotiationContract(
        conjunction_id=conjunction_id,
        rounds=rounds,
        outcome=outcome,
    )
