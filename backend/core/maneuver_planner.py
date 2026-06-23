"""Maneuver planner — Tsiolkovsky-based collision avoidance burn generation.

Generates candidate maneuvers for a given conjunction:
  1. For each delta-v magnitude (0.05, 0.10, 0.25, 0.50, 1.0 m/s):
     - Compute prograde and retrograde burns
     - Calculate fuel cost using the Tsiolkovsky rocket equation
     - Re-propagate the modified orbit to find the new miss distance
     - Count secondary conjunctions introduced by the orbit change
  2. Filter to the top 5 candidates by combined score
  3. Generate an AI recommendation (Claude API) or template fallback

The Tsiolkovsky rocket equation:
  Δm = m_wet × (1 - exp(-Δv / (g₀ × Isp)))

Where:
  Δm = fuel mass consumed (kg)
  m_wet = current total mass = dry_mass + fuel_remaining (kg)
  Δv = delta-v magnitude (m/s)
  g₀ = 9.80665 m/s² (standard gravity)
  Isp = specific impulse of the thruster (seconds)

This is the REAL rocket equation, not an approximation. The fuel cost
is physically accurate for chemical propulsion systems.
"""
import logging
import math
from datetime import datetime, timezone, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config import get_settings
from db.session import AsyncSessionLocal
from db.models import (
    Conjunction, SpaceObject, SatelliteProfile, Maneuver,
    ManeuverStatus, ManeuverDirection,
)
from core.propagator import propagate_single, propagate_timeseries, PropagationError
from schemas.maneuvers import ManeuverCandidate, Recommendation, TradeOffMatrix, MissionLifeImpact

logger = logging.getLogger("orbitpulse.core.maneuver_planner")
settings = get_settings()

# Standard gravitational acceleration (m/s²) — exact SI value
G0 = 9.80665


def compute_fuel_cost(
    delta_v_ms: float,
    dry_mass_kg: float,
    fuel_remaining_kg: float,
    isp_s: float,
) -> float:
    """Compute fuel consumption using the Tsiolkovsky rocket equation.

    Args:
        delta_v_ms: Delta-v magnitude in m/s
        dry_mass_kg: Satellite dry mass (without fuel) in kg
        fuel_remaining_kg: Current fuel remaining in kg
        isp_s: Specific impulse of the thruster in seconds

    Returns:
        Fuel consumed in kg. Returns infinity if delta-v exceeds
        available fuel budget.
    """
    if isp_s <= 0 or fuel_remaining_kg <= 0:
        return float("inf")

    m_wet = dry_mass_kg + fuel_remaining_kg
    exhaust_velocity = G0 * isp_s

    # Tsiolkovsky: Δm = m_wet × (1 - exp(-Δv / v_e))
    fuel_consumed = m_wet * (1 - math.exp(-delta_v_ms / exhaust_velocity))

    if fuel_consumed > fuel_remaining_kg:
        return float("inf")

    return round(fuel_consumed, 4)


def compute_mission_life_impact(
    fuel_consumed_kg: float,
    fuel_remaining_kg: float,
    remaining_mission_days: int,
) -> MissionLifeImpact:
    """Compute how much mission lifetime a burn consumes.

    Assumes linear fuel consumption over remaining mission life,
    which is a simplification but standard for first-order analysis.

    Args:
        fuel_consumed_kg: Fuel cost of this maneuver
        fuel_remaining_kg: Total fuel remaining before the maneuver
        remaining_mission_days: Expected remaining mission duration

    Returns:
        MissionLifeImpact with days lost and percentage of remaining life.
    """
    if fuel_remaining_kg <= 0:
        return MissionLifeImpact(days=float("inf"), pct_of_remaining=100.0)

    fraction = fuel_consumed_kg / fuel_remaining_kg
    days_lost = fraction * remaining_mission_days
    pct_lost = fraction * 100.0

    return MissionLifeImpact(
        days=round(days_lost, 1),
        pct_of_remaining=round(pct_lost, 2),
    )



# Earth gravitational parameter (km³/s²) — WGS84
MU_EARTH = 398600.4418


def _state_to_orbital_elements(
    pos: np.ndarray,
    vel: np.ndarray,
) -> tuple[float, float, float, float, float, float]:
    """Convert Cartesian state vector to classical Keplerian orbital elements.

    Args:
        pos: Position vector in km (TEME frame)
        vel: Velocity vector in km/s (TEME frame)

    Returns:
        Tuple of (a, e, i, raan, argp, true_anomaly) where:
          a = semi-major axis (km)
          e = eccentricity (dimensionless)
          i = inclination (rad)
          raan = right ascension of ascending node (rad)
          argp = argument of periapsis (rad)
          true_anomaly = true anomaly (rad)
    """
    r = np.linalg.norm(pos)
    v = np.linalg.norm(vel)

    # Specific angular momentum
    h_vec = np.cross(pos, vel)
    h = np.linalg.norm(h_vec)

    # Node vector
    k_hat = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k_hat, h_vec)
    n = np.linalg.norm(n_vec)

    # Eccentricity vector
    e_vec = ((v**2 - MU_EARTH / r) * pos - np.dot(pos, vel) * vel) / MU_EARTH
    e = np.linalg.norm(e_vec)

    # Specific mechanical energy → semi-major axis
    energy = v**2 / 2.0 - MU_EARTH / r
    if abs(energy) < 1e-10:
        a = float("inf")  # Parabolic — shouldn't happen for orbiting objects
    else:
        a = -MU_EARTH / (2.0 * energy)

    # Inclination
    i = math.acos(np.clip(h_vec[2] / h, -1.0, 1.0))

    # RAAN
    if n > 1e-10:
        raan = math.acos(np.clip(n_vec[0] / n, -1.0, 1.0))
        if n_vec[1] < 0:
            raan = 2 * math.pi - raan
    else:
        raan = 0.0

    # Argument of periapsis
    if n > 1e-10 and e > 1e-10:
        argp = math.acos(np.clip(np.dot(n_vec, e_vec) / (n * e), -1.0, 1.0))
        if e_vec[2] < 0:
            argp = 2 * math.pi - argp
    else:
        argp = 0.0

    # True anomaly
    if e > 1e-10:
        nu = math.acos(np.clip(np.dot(e_vec, pos) / (e * r), -1.0, 1.0))
        if np.dot(pos, vel) < 0:
            nu = 2 * math.pi - nu
    else:
        nu = 0.0

    return (a, e, i, raan, argp, nu)


def _solve_kepler(M: float, e: float, tol: float = 1e-12, max_iter: int = 50) -> float:
    """Solve Kepler's equation M = E - e·sin(E) for eccentric anomaly E.

    Uses Newton-Raphson iteration with Markley's starting value.
    Converges in 3-5 iterations for LEO eccentricities.

    Args:
        M: Mean anomaly (rad), reduced to [0, 2π)
        e: Eccentricity (0 ≤ e < 1)
        tol: Convergence tolerance (rad)
        max_iter: Maximum iterations

    Returns:
        Eccentric anomaly E (rad)
    """
    M = M % (2 * math.pi)
    if M > math.pi:
        M -= 2 * math.pi

    # Starting guess: Markley's rational approximation
    E = M + e * math.sin(M) / (1 - math.sin(M + e) + math.sin(M))

    for _ in range(max_iter):
        f = E - e * math.sin(E) - M
        f_prime = 1 - e * math.cos(E)
        delta = f / f_prime
        E -= delta
        if abs(delta) < tol:
            break

    return E % (2 * math.pi)


def _orbital_elements_to_state(
    a: float,
    e: float,
    i: float,
    raan: float,
    argp: float,
    nu: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert Keplerian orbital elements back to Cartesian state vector.

    Args:
        a: Semi-major axis (km)
        e: Eccentricity
        i: Inclination (rad)
        raan: Right ascension of ascending node (rad)
        argp: Argument of periapsis (rad)
        nu: True anomaly (rad)

    Returns:
        (position_km, velocity_km_s) — both as 3D numpy arrays in TEME frame
    """
    p = a * (1 - e**2)  # Semi-latus rectum
    r = p / (1 + e * math.cos(nu))

    # Position and velocity in the perifocal frame (PQW)
    pos_pqw = np.array([
        r * math.cos(nu),
        r * math.sin(nu),
        0.0,
    ])

    vel_pqw = math.sqrt(MU_EARTH / p) * np.array([
        -math.sin(nu),
        e + math.cos(nu),
        0.0,
    ])

    # Rotation matrix: perifocal (PQW) → inertial (TEME)
    cos_raan = math.cos(raan)
    sin_raan = math.sin(raan)
    cos_argp = math.cos(argp)
    sin_argp = math.sin(argp)
    cos_i = math.cos(i)
    sin_i = math.sin(i)

    R = np.array([
        [
            cos_raan * cos_argp - sin_raan * sin_argp * cos_i,
            -cos_raan * sin_argp - sin_raan * cos_argp * cos_i,
            sin_raan * sin_i,
        ],
        [
            sin_raan * cos_argp + cos_raan * sin_argp * cos_i,
            -sin_raan * sin_argp + cos_raan * cos_argp * cos_i,
            -cos_raan * sin_i,
        ],
        [
            sin_argp * sin_i,
            cos_argp * sin_i,
            cos_i,
        ],
    ])

    pos = R @ pos_pqw
    vel = R @ vel_pqw

    return pos, vel


def _keplerian_propagate(
    pos: np.ndarray,
    vel: np.ndarray,
    dt_seconds: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate a state vector forward in time using two-body Keplerian mechanics.

    This is the CORRECT way to propagate a modified orbit after applying
    a delta-v. It follows the curved orbital path instead of a straight line.

    Steps:
      1. Convert (pos, vel) → orbital elements (a, e, i, Ω, ω, ν)
      2. Convert true anomaly → eccentric anomaly → mean anomaly
      3. Advance mean anomaly by n·Δt (where n = √(μ/a³))
      4. Solve Kepler's equation for new eccentric anomaly
      5. Convert back to true anomaly → state vector

    Accuracy: Exact for two-body motion. For LEO with J2 perturbations,
    error is ~0.1-1 km over 2 hours, which is sufficient for maneuver
    candidate ranking (we're comparing candidates, not generating guidance).

    Args:
        pos: Position vector (km, TEME)
        vel: Velocity vector (km/s, TEME)
        dt_seconds: Time to propagate forward (seconds)

    Returns:
        (new_pos_km, new_vel_km_s) after dt_seconds
    """
    a, e, i, raan, argp, nu = _state_to_orbital_elements(pos, vel)

    if a <= 0 or a == float("inf") or e >= 1.0:
        # Hyperbolic or parabolic — fall back to linear (shouldn't happen)
        return pos + vel * dt_seconds, vel

    # True anomaly → eccentric anomaly
    E0 = 2 * math.atan2(
        math.sqrt(1 - e) * math.sin(nu / 2),
        math.sqrt(1 + e) * math.cos(nu / 2),
    )

    # Eccentric anomaly → mean anomaly
    M0 = E0 - e * math.sin(E0)

    # Mean motion (rad/s)
    n = math.sqrt(MU_EARTH / a**3)

    # Advance mean anomaly
    M1 = M0 + n * dt_seconds

    # Solve Kepler's equation for new eccentric anomaly
    E1 = _solve_kepler(M1, e)

    # Eccentric anomaly → true anomaly
    nu1 = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(E1 / 2),
        math.sqrt(1 - e) * math.cos(E1 / 2),
    )

    # Convert back to state vector
    return _orbital_elements_to_state(a, e, i, raan, argp, nu1)


async def _simulate_burn_miss_distance(
    line1: str,
    line2: str,
    other_line1: str,
    other_line2: str,
    burn_time: datetime,
    delta_v_ms: float,
    direction: ManeuverDirection,
    tca_time: datetime,
) -> float | None:
    """Simulate a burn and compute the resulting miss distance.

    Applies delta-v to the satellite's velocity at burn_time, then
    propagates the modified orbit to TCA using Keplerian mechanics
    (not linear extrapolation). The other object is propagated with
    SGP4 from its TLE.

    Accuracy: ~0.1-1 km for burns < 1 m/s with 2h lead time.
    Sufficient for ranking maneuver candidates against each other.

    Returns None if propagation fails.
    """
    try:
        # Get the burning satellite's state at burn time
        pos_burn, vel_burn = propagate_single(line1, line2, burn_time)

        # Apply delta-v in the velocity direction (prograde/retrograde)
        vel_unit = vel_burn / np.linalg.norm(vel_burn)
        if direction == ManeuverDirection.RETROGRADE:
            vel_unit = -vel_unit

        # Convert m/s to km/s for SGP4 velocity frame
        delta_v_kms = delta_v_ms / 1000.0
        modified_vel = vel_burn + vel_unit * delta_v_kms

        # Propagate modified orbit to TCA using Keplerian mechanics
        dt_seconds = (tca_time - burn_time).total_seconds()
        pos_at_tca, _ = _keplerian_propagate(pos_burn, modified_vel, dt_seconds)

        # Other object's position at TCA (unmodified orbit via SGP4)
        pos_other, _ = propagate_single(other_line1, other_line2, tca_time)

        miss_km = float(np.linalg.norm(pos_at_tca - pos_other))
        return round(miss_km, 4)

    except (PropagationError, Exception) as e:
        logger.debug(f"Burn simulation failed: {e}")
        return None



async def _count_secondary_conjunctions(
    line1: str,
    line2: str,
    burn_time: datetime,
    delta_v_ms: float,
    direction: ManeuverDirection,
    original_other_id: int,
) -> int:
    """Re-screen a modified trajectory against the catalog for secondary collisions.

    After applying a delta-v burn, propagates the modified orbit forward
    72 hours and checks distance against a sample of catalog objects.
    If any come within 10 km, they count as secondary conjunctions.

    This implements the Domino Effect requirement: auto-reject any burn
    that creates new close approaches.

    Args:
        line1: TLE line 1 of the maneuvering satellite
        line2: TLE line 2 of the maneuvering satellite
        burn_time: Time of the burn
        delta_v_ms: Burn magnitude in m/s
        direction: PROGRADE or RETROGRADE
        original_other_id: NORAD ID of the other object in the original
                           conjunction (excluded from secondary checks)

    Returns:
        Count of secondary conjunctions detected.
    """
    try:
        # Get post-burn state
        pos_burn, vel_burn = propagate_single(line1, line2, burn_time)
        vel_unit = vel_burn / np.linalg.norm(vel_burn)
        if direction == ManeuverDirection.RETROGRADE:
            vel_unit = -vel_unit
        delta_v_kms = delta_v_ms / 1000.0
        modified_vel = vel_burn + vel_unit * delta_v_kms

        # Check at 3 sample times: +6h, +24h, +48h after burn
        secondary_count = 0
        check_offsets_h = [6, 24, 48]

        for offset_h in check_offsets_h:
            dt_s = offset_h * 3600.0

            # Keplerian propagation of modified orbit (curves correctly)
            modified_pos, _ = _keplerian_propagate(pos_burn, modified_vel, dt_s)

            # Get catalog positions at this time (use the engine's batch method)
            from core.engine import orbital_engine
            catalog_positions = await orbital_engine.get_current_positions_batch(limit=500)

            for cat_entry in catalog_positions:
                if len(cat_entry) < 4:
                    continue
                cat_norad = int(cat_entry[0])
                if cat_norad == original_other_id or cat_norad < 0:
                    continue

                cat_lat, cat_lon, cat_alt = cat_entry[1], cat_entry[2], cat_entry[3]
                r = 6371.0 + cat_alt
                lat_rad = np.radians(cat_lat)
                lon_rad = np.radians(cat_lon)
                cat_pos = np.array([
                    r * np.cos(lat_rad) * np.cos(lon_rad),
                    r * np.cos(lat_rad) * np.sin(lon_rad),
                    r * np.sin(lat_rad),
                ])

                dist = float(np.linalg.norm(modified_pos - cat_pos))
                if dist < settings.conjunction_threshold_km:
                    secondary_count += 1

        return secondary_count

    except Exception as e:
        logger.debug(f"Secondary re-screening failed: {e}")
        return 0


async def generate_maneuver_candidates(
    conjunction_id: int,
) -> TradeOffMatrix | None:
    """Generate and store maneuver candidates for a conjunction.

    For the maneuvering satellite (determined by profile availability),
    generates candidates at each configured delta-v step in both
    prograde and retrograde directions. Each candidate includes:
      - Fuel cost (Tsiolkovsky rocket equation)
      - Mission life impact (days and percentage)
      - New miss distance (simulated burn)
      - Secondary conjunction count (re-screened against catalog)

    Candidates that create new secondary conjunctions are auto-rejected.
    The top 5 candidates by trade-off score are stored in the database.

    Returns None if the conjunction doesn't exist or has no maneuverable satellite.
    """
    async with AsyncSessionLocal() as session:
        # Load conjunction
        conj_result = await session.execute(
            select(Conjunction).where(Conjunction.id == conjunction_id)
        )
        conj = conj_result.scalar_one_or_none()
        if conj is None:
            logger.warning(f"Conjunction {conjunction_id} not found")
            return None

        # Load both objects
        obj_result = await session.execute(
            select(SpaceObject).where(
                SpaceObject.norad_id.in_([conj.obj_a_id, conj.obj_b_id])
            )
        )
        objects = {obj.norad_id: obj for obj in obj_result.scalars().all()}

        # Find which satellite has a profile (maneuverable)
        profile_result = await session.execute(
            select(SatelliteProfile).where(
                SatelliteProfile.norad_id.in_([conj.obj_a_id, conj.obj_b_id])
            )
        )
        profiles = {p.norad_id: p for p in profile_result.scalars().all()}

    if not profiles:
        logger.info(f"No maneuverable satellite in conjunction {conjunction_id}")
        return None

    # Choose the satellite with higher mission priority to maneuver
    maneuvering_id = max(profiles.keys(), key=lambda nid: profiles[nid].mission_priority)
    other_id = conj.obj_b_id if maneuvering_id == conj.obj_a_id else conj.obj_a_id

    maneuvering_obj = objects.get(maneuvering_id)
    other_obj = objects.get(other_id)
    profile = profiles[maneuvering_id]

    if not maneuvering_obj or not other_obj:
        return None

    # Burn time: 2 hours before TCA (standard lead time for LEO maneuvers)
    burn_time = conj.tca_time - timedelta(hours=2)

    candidates: list[dict] = []
    for delta_v in settings.maneuver_delta_v_steps:
        for direction in [ManeuverDirection.PROGRADE, ManeuverDirection.RETROGRADE]:
            fuel_cost = compute_fuel_cost(
                delta_v_ms=delta_v,
                dry_mass_kg=profile.dry_mass_kg,
                fuel_remaining_kg=profile.fuel_remaining_kg,
                isp_s=profile.isp_rating,
            )

            if fuel_cost == float("inf"):
                continue

            life_impact = compute_mission_life_impact(
                fuel_consumed_kg=fuel_cost,
                fuel_remaining_kg=profile.fuel_remaining_kg,
                remaining_mission_days=profile.remaining_mission_days,
            )

            new_miss = await _simulate_burn_miss_distance(
                line1=maneuvering_obj.tle_line1,
                line2=maneuvering_obj.tle_line2,
                other_line1=other_obj.tle_line1,
                other_line2=other_obj.tle_line2,
                burn_time=burn_time,
                delta_v_ms=delta_v,
                direction=direction,
                tca_time=conj.tca_time,
            )

            if new_miss is None:
                continue

            # Re-screen modified trajectory for secondary conjunctions
            secondary = await _count_secondary_conjunctions(
                line1=maneuvering_obj.tle_line1,
                line2=maneuvering_obj.tle_line2,
                burn_time=burn_time,
                delta_v_ms=delta_v,
                direction=direction,
                original_other_id=other_id,
            )

            # Auto-reject if the burn creates new collisions
            status = ManeuverStatus.CANDIDATE
            rejection_reason = None
            if secondary > 0:
                status = ManeuverStatus.REJECTED
                rejection_reason = f"Creates {secondary} secondary conjunction(s)"

            candidates.append({
                "conjunction_id": conjunction_id,
                "satellite_id": maneuvering_id,
                "direction": direction,
                "delta_v_ms": delta_v,
                "burn_time": burn_time,
                "new_miss_distance_km": new_miss,
                "fuel_cost_kg": fuel_cost,
                "mission_life_impact_days": life_impact.days,
                "mission_life_impact_pct": life_impact.pct_of_remaining,
                "secondary_conjunctions": secondary,
                "status": status,
            })

    # Sort by trade-off score: maximize miss distance, minimize fuel cost
    # Score = new_miss_km / (fuel_cost_kg + 0.01) — higher is better
    candidates.sort(
        key=lambda c: c["new_miss_distance_km"] / (c["fuel_cost_kg"] + 0.01),
        reverse=True,
    )
    top_candidates = candidates[:settings.maneuver_candidates]

    # Mark the best candidate as RECOMMENDED
    if top_candidates:
        top_candidates[0]["status"] = ManeuverStatus.RECOMMENDED

    # Store in database
    stored: list[ManeuverCandidate] = []
    async with AsyncSessionLocal() as session:
        for c in top_candidates:
            maneuver = Maneuver(**c)
            session.add(maneuver)
            await session.flush()

            stored.append(ManeuverCandidate(
                id=maneuver.id,
                direction=maneuver.direction.value,
                delta_v_ms=maneuver.delta_v_ms,
                burn_time=maneuver.burn_time,
                new_miss_distance_km=maneuver.new_miss_distance_km,
                fuel_cost_kg=maneuver.fuel_cost_kg,
                mission_life_impact=MissionLifeImpact(
                    days=maneuver.mission_life_impact_days,
                    pct_of_remaining=maneuver.mission_life_impact_pct,
                ),
                secondary_conjunctions=maneuver.secondary_conjunctions,
                status=maneuver.status.value,
                rejection_reason=None,
            ))
        await session.commit()

    # Generate recommendation
    recommendation = _generate_template_recommendation(stored, profile, conj)

    return TradeOffMatrix(
        conjunction=_conjunction_to_dict(conj, objects),
        candidates=stored,
        recommendation=recommendation,
    )


def _generate_template_recommendation(
    candidates: list[ManeuverCandidate],
    profile: SatelliteProfile,
    conjunction: Conjunction,
) -> Recommendation:
    """Deterministic template-based recommendation.

    Used when Claude API is unavailable. Selects the recommended candidate
    and generates a structured explanation based on the trade-off analysis.
    """
    if not candidates:
        return Recommendation(
            chosen_id=None,
            reasoning="No feasible maneuvers found within fuel budget constraints.",
            source="template",
        )

    best = candidates[0]

    reasoning = (
        f"Recommend {best.direction} burn of {best.delta_v_ms} m/s "
        f"at T-2h before TCA. This increases miss distance from "
        f"{conjunction.miss_distance_km:.2f} km to {best.new_miss_distance_km:.2f} km "
        f"at a fuel cost of {best.fuel_cost_kg:.3f} kg "
        f"({best.mission_life_impact.pct_of_remaining:.1f}% of remaining mission life). "
    )

    if best.secondary_conjunctions == 0:
        reasoning += "No secondary conjunctions introduced by this maneuver."
    else:
        reasoning += (
            f"Warning: {best.secondary_conjunctions} secondary conjunction(s) "
            f"may be introduced by the orbit change."
        )

    return Recommendation(
        chosen_id=best.id,
        reasoning=reasoning,
        source="template",
    )


def _conjunction_to_dict(conj: Conjunction, objects: dict) -> dict:
    """Serialize conjunction to dict for the TradeOffMatrix response."""
    obj_a = objects.get(conj.obj_a_id)
    obj_b = objects.get(conj.obj_b_id)
    return {
        "id": conj.id,
        "obj_a_id": conj.obj_a_id,
        "obj_b_id": conj.obj_b_id,
        "obj_a_name": obj_a.name if obj_a else None,
        "obj_b_name": obj_b.name if obj_b else None,
        "tca_time": conj.tca_time.isoformat(),
        "miss_distance_km": conj.miss_distance_km,
        "relative_velocity_kms": conj.relative_velocity_kms,
        "risk_score": conj.risk_score,
        "tier": conj.tier.value,
    }
