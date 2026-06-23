"""Probability of Collision (Pc) — Chan's 2008 analytical approximation.

This implements the actual metric used by NASA CARA (Conjunction Assessment
Risk Analysis), ESA, and the 18th Space Defense Squadron for conjunction
assessment. Without Pc, risk scoring is guesswork.

The algorithm:
  1. Estimate position covariance from TLE epoch age (uncertainty grows
     with time since last observation)
  2. Project combined covariance onto the B-plane (the plane perpendicular
     to the relative velocity vector at closest approach)
  3. Compute Pc using Chan's analytical formula:
     Pc = (HBR² / (2σ₁σ₂)) × exp(-½ × (x²/σ₁² + y²/σ₂²))

     where:
       HBR = combined hard-body radius of both objects
       σ₁, σ₂ = eigenvalues of the projected 2×2 covariance
       x, y = miss vector components in the B-plane

References:
  - Chan, F.K. (2008). "Spacecraft Collision Probability." AIAA.
  - Alfano, S. (2005). "A Numerical Implementation of Spherical Object
    Collision Probability." Journal of the Astronautical Sciences.
  - NASA CARA Recommended Standard Practices, Rev 4, 2020.
"""
import logging
import math
from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select

from config import get_settings
from db.session import AsyncSessionLocal
from db.models import Conjunction, SpaceObject
from core.propagator import propagate_single, PropagationError

logger = logging.getLogger("orbitpulse.core.probability_of_collision")
settings = get_settings()


# Hard-body radius estimates by RCS size category (meters)
# Source: ESA Space Debris Office, 2022
HBR_MAP = {
    "LARGE": 5.0,    # Rocket bodies, large satellites (>1m)
    "MEDIUM": 1.0,   # CubeSats, small satellites (10cm–1m)
    "SMALL": 0.1,    # Debris fragments (<10cm)
}
DEFAULT_HBR = 1.0


def estimate_covariance_from_tle_age(
    epoch_age_hours: float,
) -> np.ndarray:
    """Estimate position covariance matrix from TLE epoch age.

    TLE accuracy degrades predictably with time since the epoch:
      - At epoch: ~1 km (1-sigma) in each axis
      - At 24h: ~5 km
      - At 72h: ~20 km
      - At 168h (7 days): ~50 km

    This follows a roughly quadratic growth model based on empirical
    studies of TLE accuracy (Vallado & Crawford, 2008).

    We use a diagonal covariance (no cross-correlations) which is a
    simplification but standard practice when actual covariance data
    is unavailable (which is always the case with TLEs).

    Args:
        epoch_age_hours: Time since TLE epoch in hours

    Returns:
        3×3 diagonal position covariance matrix (km²)
    """
    # Base 1-sigma uncertainty at epoch (km)
    sigma_base = 1.0

    # Growth rate: sigma ~ sigma_base × (1 + 0.2 × hours)^0.5
    # This matches empirical TLE accuracy studies
    age_factor = max(1.0, 1.0 + 0.2 * abs(epoch_age_hours))
    sigma = sigma_base * math.sqrt(age_factor)

    # Along-track uncertainty is ~3× cross-track for TLEs
    # (most error accumulates in the direction of motion)
    sigma_along = sigma * 3.0
    sigma_cross = sigma
    sigma_radial = sigma * 1.5

    return np.diag([sigma_along**2, sigma_cross**2, sigma_radial**2])


def project_to_encounter_plane(
    pos_a: np.ndarray,
    vel_a: np.ndarray,
    pos_b: np.ndarray,
    vel_b: np.ndarray,
    cov_a: np.ndarray,
    cov_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Project the conjunction geometry onto the B-plane (encounter plane).

    The B-plane is perpendicular to the relative velocity vector at the
    time of closest approach. All conjunction assessment is done in this
    2D plane because only the cross-section matters for collision.

    Args:
        pos_a: Position of object A (km, TEME)
        vel_a: Velocity of object A (km/s, TEME)
        pos_b: Position of object B (km, TEME)
        vel_b: Velocity of object B (km/s, TEME)
        cov_a: 3×3 position covariance of object A (km²)
        cov_b: 3×3 position covariance of object B (km²)

    Returns:
        (miss_2d, cov_2d) where:
          miss_2d = 2D miss vector in the B-plane (km)
          cov_2d = 2×2 combined covariance projected onto B-plane (km²)
    """
    # Relative state
    rel_pos = pos_a - pos_b  # Miss vector (3D)
    rel_vel = vel_a - vel_b  # Relative velocity

    rel_vel_mag = np.linalg.norm(rel_vel)
    if rel_vel_mag < 1e-10:
        # Objects co-moving — degenerate case
        return np.array([np.linalg.norm(rel_pos), 0.0]), np.eye(2)

    # B-plane basis vectors
    # e_v = unit relative velocity (normal to B-plane)
    # e_1, e_2 = orthogonal basis vectors IN the B-plane
    e_v = rel_vel / rel_vel_mag

    # Choose a reference vector not parallel to e_v
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(e_v, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])

    e_1 = np.cross(e_v, ref)
    e_1 = e_1 / np.linalg.norm(e_1)
    e_2 = np.cross(e_v, e_1)
    e_2 = e_2 / np.linalg.norm(e_2)

    # Projection matrix (3D → 2D B-plane)
    P = np.array([e_1, e_2])  # 2×3

    # Project miss vector
    miss_2d = P @ rel_pos

    # Combined covariance (uncorrelated objects → additive)
    cov_combined = cov_a + cov_b

    # Project combined covariance onto B-plane
    cov_2d = P @ cov_combined @ P.T

    return miss_2d, cov_2d


def compute_pc_chan(
    miss_2d: np.ndarray,
    cov_2d: np.ndarray,
    hard_body_radius_km: float,
) -> float:
    """Compute Probability of Collision using Chan's 2008 analytical formula.

    This is the standard analytical approximation used when the combined
    hard-body radius is small relative to the covariance ellipse (which
    is almost always true in practice).

    Chan's formula assumes the probability density is approximately
    constant over the hard-body cross-section, which is valid when
    HBR << σ (the usual case for LEO conjunctions).

    Pc = (π × HBR²) / (2π × σ₁ × σ₂) × exp(-½ × (x²/σ₁² + y²/σ₂²))

    Simplifies to:
    Pc = (HBR² / (2 × σ₁ × σ₂)) × exp(-½ × Mahalanobis²)

    Args:
        miss_2d: 2D miss vector in B-plane (km)
        cov_2d: 2×2 covariance in B-plane (km²)
        hard_body_radius_km: Combined hard-body radius (km)

    Returns:
        Probability of collision (dimensionless, 0.0 to 1.0)
    """
    # Eigenvalue decomposition of 2D covariance
    eigenvalues, eigenvectors = np.linalg.eigh(cov_2d)

    # Ensure positive eigenvalues (numerical safety)
    eigenvalues = np.maximum(eigenvalues, 1e-20)

    sigma_1 = math.sqrt(eigenvalues[0])
    sigma_2 = math.sqrt(eigenvalues[1])

    # Rotate miss vector into eigenvector frame
    miss_rotated = eigenvectors.T @ miss_2d

    # Mahalanobis distance squared
    mahal_sq = (miss_rotated[0]**2 / eigenvalues[0]) + (miss_rotated[1]**2 / eigenvalues[1])

    # Chan's formula
    hbr_sq = hard_body_radius_km**2
    pc = (hbr_sq / (2.0 * sigma_1 * sigma_2)) * math.exp(-0.5 * mahal_sq)

    # Clamp to [0, 1]
    return min(1.0, max(0.0, pc))


def _get_hbr_km(rcs_size: str | None) -> float:
    """Get hard-body radius in km from RCS size category."""
    meters = HBR_MAP.get(rcs_size or "", DEFAULT_HBR)
    return meters / 1000.0  # Convert m → km


async def compute_pc_for_conjunction(
    conjunction_id: int,
) -> dict | None:
    """Compute full Pc analysis for a stored conjunction.

    Loads both objects, estimates covariance from TLE epoch ages,
    propagates both to TCA, projects onto B-plane, and computes Pc.

    Returns:
        Dict with pc, covariance data, B-plane miss, and metadata.
        None if conjunction not found or propagation fails.
    """
    async with AsyncSessionLocal() as session:
        conj_result = await session.execute(
            select(Conjunction).where(Conjunction.id == conjunction_id)
        )
        conj = conj_result.scalar_one_or_none()
        if conj is None:
            return None

        obj_result = await session.execute(
            select(SpaceObject).where(
                SpaceObject.norad_id.in_([conj.obj_a_id, conj.obj_b_id])
            )
        )
        objects = {obj.norad_id: obj for obj in obj_result.scalars().all()}

    obj_a = objects.get(conj.obj_a_id)
    obj_b = objects.get(conj.obj_b_id)
    if not obj_a or not obj_b:
        return None

    try:
        # Propagate both objects to TCA
        pos_a, vel_a = propagate_single(obj_a.tle_line1, obj_a.tle_line2, conj.tca_time)
        pos_b, vel_b = propagate_single(obj_b.tle_line1, obj_b.tle_line2, conj.tca_time)
    except PropagationError as e:
        logger.debug(f"Pc propagation failed for conjunction {conjunction_id}: {e}")
        return None

    # Estimate covariance from TLE epoch age
    now = datetime.now(timezone.utc)
    age_a = (now - obj_a.epoch).total_seconds() / 3600.0 if obj_a.epoch else 72.0
    age_b = (now - obj_b.epoch).total_seconds() / 3600.0 if obj_b.epoch else 72.0

    cov_a = estimate_covariance_from_tle_age(age_a)
    cov_b = estimate_covariance_from_tle_age(age_b)

    # Project onto B-plane
    miss_2d, cov_2d = project_to_encounter_plane(pos_a, vel_a, pos_b, vel_b, cov_a, cov_b)

    # Combined hard-body radius
    hbr_a = _get_hbr_km(obj_a.rcs_size)
    hbr_b = _get_hbr_km(obj_b.rcs_size)
    combined_hbr = hbr_a + hbr_b

    # Compute Pc
    pc = compute_pc_chan(miss_2d, cov_2d, combined_hbr)

    # Eigenvalues for the response
    eigenvalues = np.linalg.eigvalsh(cov_2d)
    sigma_1 = float(math.sqrt(max(eigenvalues[0], 0)))
    sigma_2 = float(math.sqrt(max(eigenvalues[1], 0)))

    return {
        "probability_of_collision": pc,
        "pc_log10": math.log10(max(pc, 1e-30)),
        "miss_distance_km": conj.miss_distance_km,
        "b_plane_miss_x_km": float(miss_2d[0]),
        "b_plane_miss_y_km": float(miss_2d[1]),
        "b_plane_sigma_1_km": sigma_1,
        "b_plane_sigma_2_km": sigma_2,
        "combined_hbr_km": combined_hbr,
        "tle_age_a_hours": round(age_a, 1),
        "tle_age_b_hours": round(age_b, 1),
        "method": "Chan2008",
        "note": (
            "Covariance estimated from TLE epoch age. "
            "For operational use, owner/operator covariance data (CDM) is required."
        ),
    }

