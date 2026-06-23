"""Risk scoring and triage tier assignment.

The risk score combines four factors:
  1. Miss distance (50% weight) — inverse exponential decay from threshold
  2. Relative velocity (30% weight) — linear scaling, 15 km/s = 1.0
  3. Object size (20% weight) — based on RCS (LARGE=1.0, MEDIUM=0.6, SMALL=0.3)
  4. Trend multiplier (±30%) — convergence (decreasing miss) amplifies score,
     divergence (increasing miss) attenuates score

The trend is applied as a post-multiplier, NOT an additive factor.
This prevents low-base inflation: a distant conjunction with a converging
trend should not manufacture an ACTION alert.

Triage tiers:
  ACTION:    risk >= 0.7  OR  (miss < 1 km AND velocity > 5 km/s)
  WATCHLIST: risk >= 0.3  AND  miss < 5 km
  DISMISSED: everything else

The hard-override for ACTION (miss < 1 km AND velocity > 5 km/s) ensures
that extremely close, high-speed conjunctions are never missed by the
weighted formula. This matches real-world practice where operators elevate
any sub-1km conjunction to immediate review regardless of other factors.
"""
import logging
import math

from config import get_settings
from db.models import TriageTier

logger = logging.getLogger("orbitpulse.core.risk_scoring")
settings = get_settings()


def compute_risk_score(
    miss_km: float,
    rel_vel_kms: float,
    size_a: str | None,
    size_b: str | None,
    prev_miss_km: float | None,
) -> float:
    """Compute weighted risk score for a conjunction.

    Args:
        miss_km: Closest approach distance in kilometers
        rel_vel_kms: Relative velocity at TCA in km/s
        size_a: RCS size of object A ('SMALL', 'MEDIUM', 'LARGE', or None)
        size_b: RCS size of object B ('SMALL', 'MEDIUM', 'LARGE', or None)
        prev_miss_km: Previous miss distance for trend calculation (None if first detection)

    Returns:
        Risk score in range [0.0, 1.0], where 1.0 is highest risk.
    """
    # 1. Distance factor (50% weight) — inverse exponential decay
    # Score = 1.0 at 0 km, ~0.37 at threshold, ~0.05 at 3× threshold
    threshold = settings.conjunction_threshold_km
    if threshold <= 0:
        distance_factor = 1.0
    else:
        distance_factor = math.exp(-miss_km / threshold)

    # 2. Velocity factor (30% weight) — linear scaling capped at 1.0
    # 15 km/s is the maximum expected LEO relative velocity (head-on)
    max_velocity = 15.0
    velocity_factor = min(1.0, rel_vel_kms / max_velocity)

    # 3. Size factor (20% weight) — uses the larger of the two objects
    size_map = {"LARGE": 1.0, "MEDIUM": 0.6, "SMALL": 0.3}
    size_a_val = size_map.get(size_a or "", 0.5)
    size_b_val = size_map.get(size_b or "", 0.5)
    size_factor = max(size_a_val, size_b_val)

    # Weighted combination
    raw_score = (
        0.50 * distance_factor
        + 0.30 * velocity_factor
        + 0.20 * size_factor
    )

    # 4. Trend multiplier (±30%) — convergence amplifies, divergence attenuates
    if prev_miss_km is not None and prev_miss_km > 0:
        if miss_km < prev_miss_km:
            # Converging — objects getting closer (higher risk)
            trend = 1.3
        elif miss_km > prev_miss_km:
            # Diverging — objects moving apart (lower risk)
            trend = 0.7
        else:
            trend = 1.0
    else:
        trend = 1.0

    final_score = min(1.0, max(0.0, raw_score * trend))
    return round(final_score, 4)


def assign_tier(
    risk_score: float,
    miss_km: float,
    rel_vel_kms: float,
) -> TriageTier:
    """Assign triage tier based on risk score and hard-override rules.

    Tier assignment follows strict priority:
      1. ACTION hard-override: miss < 1 km AND velocity > 5 km/s (always ACTION)
      2. ACTION threshold: risk >= 0.7
      3. WATCHLIST: risk >= 0.3 AND miss < 5 km
      4. DISMISSED: everything else

    The hard-override exists because the weighted formula can underweight
    extremely close, high-speed conjunctions if both objects are SMALL.
    A 0.5 km / 10 km/s conjunction is dangerous regardless of object size.

    Args:
        risk_score: Computed risk score (0.0-1.0)
        miss_km: Closest approach distance in km
        rel_vel_kms: Relative velocity at TCA in km/s

    Returns:
        TriageTier enum value (ACTION, WATCHLIST, or DISMISSED)
    """
    tier, _ = assign_tier_with_reason(risk_score, miss_km, rel_vel_kms)
    return tier


def assign_tier_with_reason(
    risk_score: float,
    miss_km: float,
    rel_vel_kms: float,
) -> tuple[TriageTier, str]:
    """Assign triage tier with a human-readable reason for the classification.

    Returns:
        Tuple of (TriageTier, reason_string).
    """
    # Hard override: extremely close + fast = always ACTION
    if (
        miss_km < settings.action_distance_threshold_km
        and rel_vel_kms > settings.action_velocity_threshold_kms
    ):
        return (
            TriageTier.ACTION,
            f"Hard override: miss {miss_km:.2f} km < {settings.action_distance_threshold_km} km "
            f"AND velocity {rel_vel_kms:.1f} km/s > {settings.action_velocity_threshold_kms} km/s",
        )

    # Standard threshold-based assignment
    if risk_score >= settings.action_risk_threshold:
        return (
            TriageTier.ACTION,
            f"Risk score {risk_score:.2%} exceeds ACTION threshold ({settings.action_risk_threshold:.0%})",
        )

    if (
        risk_score >= settings.watchlist_risk_threshold
        and miss_km < settings.watchlist_distance_threshold_km
    ):
        return (
            TriageTier.WATCHLIST,
            f"Risk {risk_score:.2%} ≥ {settings.watchlist_risk_threshold:.0%} "
            f"AND miss {miss_km:.2f} km < {settings.watchlist_distance_threshold_km} km",
        )

    # Build dismissal reason
    reasons: list[str] = []
    if risk_score < settings.watchlist_risk_threshold:
        reasons.append(
            f"risk {risk_score:.2%} < WATCHLIST threshold ({settings.watchlist_risk_threshold:.0%})"
        )
    if miss_km >= settings.watchlist_distance_threshold_km:
        reasons.append(
            f"miss {miss_km:.2f} km ≥ distance threshold ({settings.watchlist_distance_threshold_km} km)"
        )
    if not reasons:
        reasons.append("does not meet any escalation criteria")

    return (
        TriageTier.DISMISSED,
        f"Dismissed: {'; '.join(reasons)}",
    )

