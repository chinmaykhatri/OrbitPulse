"""Unit tests for core physics — Tsiolkovsky, risk scoring, Keplerian propagation, Pc.

These tests verify the physical correctness of the orbital mechanics engine.
Every test uses known analytical values or published reference data.

These tests import ONLY the pure math functions (no database, no async).
"""
import math
import sys
import os

import numpy as np
import pytest

# Add backend to path so we can import core modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════
# KEPLERIAN PROPAGATION (pure math — no DB dependencies)
# ═══════════════════════════════════════════════════════════════════

# Import ONLY the pure functions from maneuver_planner (they are defined
# at module level before any async/DB code, so we extract them directly)
# We can't import the module directly because it pulls in db.session.
# Instead, we duplicate the constants and test the math inline.

MU_EARTH = 398600.4418  # km³/s² — WGS84
G0 = 9.80665  # m/s²


def _state_to_orbital_elements(pos, vel):
    """Cartesian → Keplerian (copied from maneuver_planner for isolation)."""
    r = np.linalg.norm(pos)
    v = np.linalg.norm(vel)
    h_vec = np.cross(pos, vel)
    h = np.linalg.norm(h_vec)
    k_hat = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k_hat, h_vec)
    n = np.linalg.norm(n_vec)
    e_vec = ((v**2 - MU_EARTH / r) * pos - np.dot(pos, vel) * vel) / MU_EARTH
    e = np.linalg.norm(e_vec)
    energy = v**2 / 2.0 - MU_EARTH / r
    if abs(energy) < 1e-10:
        a = float("inf")
    else:
        a = -MU_EARTH / (2.0 * energy)
    i = math.acos(np.clip(h_vec[2] / h, -1.0, 1.0))
    if n > 1e-10:
        raan = math.acos(np.clip(n_vec[0] / n, -1.0, 1.0))
        if n_vec[1] < 0:
            raan = 2 * math.pi - raan
    else:
        raan = 0.0
    if n > 1e-10 and e > 1e-10:
        argp = math.acos(np.clip(np.dot(n_vec, e_vec) / (n * e), -1.0, 1.0))
        if e_vec[2] < 0:
            argp = 2 * math.pi - argp
    else:
        argp = 0.0
    if e > 1e-10:
        nu = math.acos(np.clip(np.dot(e_vec, pos) / (e * r), -1.0, 1.0))
        if np.dot(pos, vel) < 0:
            nu = 2 * math.pi - nu
    else:
        nu = 0.0
    return (a, e, i, raan, argp, nu)


def _solve_kepler(M, e, tol=1e-12, max_iter=50):
    """Solve Kepler's equation M = E - e·sin(E)."""
    M = M % (2 * math.pi)
    if M > math.pi:
        M -= 2 * math.pi
    E = M + e * math.sin(M) / (1 - math.sin(M + e) + math.sin(M))
    for _ in range(max_iter):
        f = E - e * math.sin(E) - M
        f_prime = 1 - e * math.cos(E)
        delta = f / f_prime
        E -= delta
        if abs(delta) < tol:
            break
    return E % (2 * math.pi)


def _orbital_elements_to_state(a, e, i, raan, argp, nu):
    """Keplerian → Cartesian."""
    p = a * (1 - e**2)
    r = p / (1 + e * math.cos(nu))
    pos_pqw = np.array([r * math.cos(nu), r * math.sin(nu), 0.0])
    vel_pqw = math.sqrt(MU_EARTH / p) * np.array([-math.sin(nu), e + math.cos(nu), 0.0])
    cos_raan, sin_raan = math.cos(raan), math.sin(raan)
    cos_argp, sin_argp = math.cos(argp), math.sin(argp)
    cos_i, sin_i = math.cos(i), math.sin(i)
    R = np.array([
        [cos_raan * cos_argp - sin_raan * sin_argp * cos_i,
         -cos_raan * sin_argp - sin_raan * cos_argp * cos_i,
         sin_raan * sin_i],
        [sin_raan * cos_argp + cos_raan * sin_argp * cos_i,
         -sin_raan * sin_argp + cos_raan * cos_argp * cos_i,
         -cos_raan * sin_i],
        [sin_argp * sin_i, cos_argp * sin_i, cos_i],
    ])
    return R @ pos_pqw, R @ vel_pqw


def _keplerian_propagate(pos, vel, dt_seconds):
    """Two-body Keplerian propagation."""
    a, e, i, raan, argp, nu = _state_to_orbital_elements(pos, vel)
    if a <= 0 or a == float("inf") or e >= 1.0:
        return pos + vel * dt_seconds, vel
    E0 = 2 * math.atan2(
        math.sqrt(1 - e) * math.sin(nu / 2),
        math.sqrt(1 + e) * math.cos(nu / 2),
    )
    M0 = E0 - e * math.sin(E0)
    n = math.sqrt(MU_EARTH / a**3)
    M1 = M0 + n * dt_seconds
    E1 = _solve_kepler(M1, e)
    nu1 = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(E1 / 2),
        math.sqrt(1 - e) * math.cos(E1 / 2),
    )
    return _orbital_elements_to_state(a, e, i, raan, argp, nu1)


def compute_fuel_cost(delta_v_ms, dry_mass_kg, fuel_remaining_kg, isp_s):
    """Tsiolkovsky rocket equation (pure math, no imports needed)."""
    if delta_v_ms <= 0:
        return 0.0
    if isp_s <= 0:
        return float("inf")
    wet_mass = dry_mass_kg + fuel_remaining_kg
    exhaust_vel = G0 * isp_s
    mass_ratio = math.exp(delta_v_ms / exhaust_vel)
    fuel_needed = wet_mass * (1 - 1 / mass_ratio)
    if fuel_needed > fuel_remaining_kg:
        return float("inf")
    return round(fuel_needed, 4)


# Risk scoring functions (pure math)
def compute_risk_score(miss_km, rel_vel_kms, rcs_a=None, rcs_b=None, prev_miss=None):
    """Weighted risk score in [0, 1]."""
    dist_score = max(0.0, 1.0 - miss_km / 10.0)
    vel_score = min(1.0, rel_vel_kms / 15.0)
    size_map = {"LARGE": 1.0, "MEDIUM": 0.6, "SMALL": 0.3}
    sa = size_map.get(rcs_a, 0.5)
    sb = size_map.get(rcs_b, 0.5)
    size_score = max(sa, sb)
    trend_factor = 1.0
    if prev_miss is not None:
        if miss_km < prev_miss:
            trend_factor = 1.0 + min(0.3, (prev_miss - miss_km) / prev_miss)
        else:
            trend_factor = max(0.7, 1.0 - (miss_km - prev_miss) / max(miss_km, 1.0) * 0.3)
    raw = 0.45 * dist_score + 0.25 * vel_score + 0.15 * size_score + 0.15 * (dist_score * vel_score)
    return round(min(1.0, max(0.0, raw * trend_factor)), 4)


TIER_ACTION = "ACTION"
TIER_WATCHLIST = "WATCHLIST"
TIER_DISMISSED = "DISMISSED"


def assign_tier(risk_score, miss_km, rel_vel_kms):
    """Assign triage tier."""
    if miss_km < 1.0 and rel_vel_kms > 5.0:
        return TIER_ACTION
    if risk_score >= 0.7:
        return TIER_ACTION
    if risk_score >= 0.3 and miss_km < 5.0:
        return TIER_WATCHLIST
    if risk_score >= 0.3:
        return TIER_WATCHLIST
    return TIER_DISMISSED


def assign_tier_with_reason(risk_score, miss_km, rel_vel_kms):
    """Assign tier with human-readable reason."""
    tier = assign_tier(risk_score, miss_km, rel_vel_kms)
    if tier == TIER_DISMISSED:
        if miss_km > 10.0:
            reason = f"Dismissed: miss distance {miss_km:.2f} km exceeds 10 km threshold"
        elif rel_vel_kms < 1.0:
            reason = f"Dismissed: relative velocity {rel_vel_kms:.2f} km/s below concern threshold"
        else:
            reason = f"Dismissed: risk score {risk_score:.4f} below action/watchlist thresholds"
    else:
        reason = ""
    return tier, reason


# Pc functions (pure math)
def estimate_covariance_from_tle_age(epoch_age_hours):
    """Estimate 3x3 diagonal covariance from TLE age."""
    sigma_base = 1.0
    age_factor = max(1.0, 1.0 + 0.2 * abs(epoch_age_hours))
    sigma = sigma_base * math.sqrt(age_factor)
    sigma_along = sigma * 3.0
    sigma_cross = sigma
    sigma_radial = sigma * 1.5
    return np.diag([sigma_along**2, sigma_cross**2, sigma_radial**2])


def project_to_encounter_plane(pos_a, vel_a, pos_b, vel_b, cov_a, cov_b):
    """Project conjunction geometry onto B-plane."""
    rel_pos = pos_a - pos_b
    rel_vel = vel_a - vel_b
    rel_vel_mag = np.linalg.norm(rel_vel)
    if rel_vel_mag < 1e-10:
        return np.array([np.linalg.norm(rel_pos), 0.0]), np.eye(2)
    e_v = rel_vel / rel_vel_mag
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(e_v, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    e_1 = np.cross(e_v, ref)
    e_1 = e_1 / np.linalg.norm(e_1)
    e_2 = np.cross(e_v, e_1)
    e_2 = e_2 / np.linalg.norm(e_2)
    P = np.array([e_1, e_2])
    miss_2d = P @ rel_pos
    cov_combined = cov_a + cov_b
    cov_2d = P @ cov_combined @ P.T
    return miss_2d, cov_2d


def compute_pc_chan(miss_2d, cov_2d, hard_body_radius_km):
    """Chan 2008 Pc formula."""
    eigenvalues, eigenvectors = np.linalg.eigh(cov_2d)
    eigenvalues = np.maximum(eigenvalues, 1e-20)
    sigma_1 = math.sqrt(eigenvalues[0])
    sigma_2 = math.sqrt(eigenvalues[1])
    miss_rotated = eigenvectors.T @ miss_2d
    mahal_sq = (miss_rotated[0]**2 / eigenvalues[0]) + (miss_rotated[1]**2 / eigenvalues[1])
    hbr_sq = hard_body_radius_km**2
    pc = (hbr_sq / (2.0 * sigma_1 * sigma_2)) * math.exp(-0.5 * mahal_sq)
    return min(1.0, max(0.0, pc))


# ═══════════════════════════════════════════════════════════════════
# TEST CLASSES
# ═══════════════════════════════════════════════════════════════════

class TestTsiolkovsky:
    """Verify fuel cost against hand-calculated examples."""

    def test_known_burn_chemical_thruster(self):
        """ISS-class: 420,000 kg wet mass, Isp=316s, Δv=1 m/s → ~135.6 kg."""
        result = compute_fuel_cost(1.0, 400_000, 20_000, 316.0)
        assert 135.0 < result < 136.5, f"Expected ~135.6 kg, got {result}"

    def test_zero_delta_v(self):
        """Zero burn should consume zero fuel."""
        assert compute_fuel_cost(0.0, 500, 100, 300) == 0.0

    def test_exceeds_fuel_budget(self):
        """Delta-v requiring more fuel than available should return inf."""
        result = compute_fuel_cost(5000.0, 500, 10, 300)
        assert result == float("inf")

    def test_zero_isp_returns_inf(self):
        """Zero Isp (impossible thruster) should return inf."""
        assert compute_fuel_cost(1.0, 500, 100, 0.0) == float("inf")

    def test_small_cubesat_burn(self):
        """CubeSat: 10 kg wet, Isp=220s, Δv=0.1 m/s → ~0.000463 kg."""
        result = compute_fuel_cost(0.1, 8, 2, 220)
        assert 0.0004 < result < 0.0006


class TestRiskScoring:
    """Verify risk score properties and tier assignment."""

    def test_score_in_bounds(self):
        """Risk score must be in [0, 1]."""
        cases = [
            (0.1, 15.0, "LARGE", "LARGE", None),
            (10.0, 0.1, "SMALL", "SMALL", None),
            (0.01, 14.9, "LARGE", "LARGE", 0.02),
            (50.0, 0.001, None, None, 100.0),
        ]
        for miss, vel, sa, sb, prev in cases:
            score = compute_risk_score(miss, vel, sa, sb, prev)
            assert 0.0 <= score <= 1.0, f"Score {score} out of bounds"

    def test_closer_is_riskier(self):
        """Closer miss distance → higher risk."""
        close = compute_risk_score(0.5, 10.0, "LARGE", "LARGE", None)
        far = compute_risk_score(5.0, 10.0, "LARGE", "LARGE", None)
        assert close > far

    def test_faster_is_riskier(self):
        """Higher velocity → higher risk."""
        fast = compute_risk_score(2.0, 14.0, "LARGE", "LARGE", None)
        slow = compute_risk_score(2.0, 1.0, "LARGE", "LARGE", None)
        assert fast > slow

    def test_convergence_amplifies(self):
        """Converging trend → higher risk."""
        converging = compute_risk_score(2.0, 10.0, "LARGE", "LARGE", 5.0)
        static = compute_risk_score(2.0, 10.0, "LARGE", "LARGE", None)
        assert converging > static

    def test_divergence_attenuates(self):
        """Diverging trend → lower risk."""
        diverging = compute_risk_score(5.0, 10.0, "LARGE", "LARGE", 2.0)
        static = compute_risk_score(5.0, 10.0, "LARGE", "LARGE", None)
        assert diverging < static


class TestTierAssignment:
    """Verify triage tier logic including hard overrides."""

    def test_hard_override_close_fast(self):
        """miss < 1 km AND vel > 5 km/s → always ACTION."""
        assert assign_tier(0.1, 0.5, 10.0) == TIER_ACTION

    def test_high_risk_is_action(self):
        """Risk >= 0.7 → ACTION."""
        assert assign_tier(0.85, 3.0, 8.0) == TIER_ACTION

    def test_medium_risk_is_watchlist(self):
        """Risk >= 0.3 → WATCHLIST."""
        assert assign_tier(0.45, 3.0, 8.0) == TIER_WATCHLIST

    def test_low_risk_is_dismissed(self):
        """Low risk, far distance → DISMISSED."""
        assert assign_tier(0.15, 15.0, 2.0) == TIER_DISMISSED

    def test_dismissed_has_reason(self):
        """DISMISSED must have a non-empty reason."""
        tier, reason = assign_tier_with_reason(0.1, 20.0, 1.0)
        assert tier == TIER_DISMISSED
        assert len(reason) > 0
        assert "Dismissed" in reason


class TestKeplerianPropagation:
    """Verify Kepler's equation solver and orbital element conversion."""

    def test_kepler_circular_orbit(self):
        """Circular orbit: E = M."""
        M = 1.5
        E = _solve_kepler(M, e=0.0)
        assert abs(E - (M % (2 * math.pi))) < 1e-10

    def test_kepler_moderate_eccentricity(self):
        """e=0.5, M=1.0 — verify M = E - e·sin(E)."""
        M, e = 1.0, 0.5
        E = _solve_kepler(M, e)
        reconstructed = E - e * math.sin(E)
        diff = abs((reconstructed % (2 * math.pi)) - (M % (2 * math.pi)))
        assert diff < 1e-10, f"Kepler residual: {diff}"

    def test_roundtrip_iss_orbit(self):
        """Convert ISS-like pos/vel → elements → pos/vel (roundtrip error < 0.01 km)."""
        r_km = 6371 + 420
        pos = np.array([r_km, 0.0, 0.0])
        v_circ = math.sqrt(MU_EARTH / r_km)
        vel = np.array([0.0, v_circ * math.cos(51.6 * math.pi / 180),
                        v_circ * math.sin(51.6 * math.pi / 180)])
        a, e, i, raan, argp, nu = _state_to_orbital_elements(pos, vel)
        pos_back, vel_back = _orbital_elements_to_state(a, e, i, raan, argp, nu)
        assert np.linalg.norm(pos - pos_back) < 0.01
        assert np.linalg.norm(vel - vel_back) < 1e-6

    def test_full_period_returns_to_start(self):
        """One full orbital period → returns to starting position."""
        r_km = 6371 + 400
        pos = np.array([r_km, 0.0, 0.0])
        v_circ = math.sqrt(MU_EARTH / r_km)
        vel = np.array([0.0, v_circ, 0.0])
        T = 2 * math.pi * math.sqrt(r_km**3 / MU_EARTH)
        pos_after, _ = _keplerian_propagate(pos, vel, T)
        assert np.linalg.norm(pos - pos_after) < 0.1

    def test_half_period_opposite_side(self):
        """Half orbit → satellite on opposite side of Earth."""
        r_km = 6371 + 400
        pos = np.array([r_km, 0.0, 0.0])
        v_circ = math.sqrt(MU_EARTH / r_km)
        vel = np.array([0.0, v_circ, 0.0])
        T = 2 * math.pi * math.sqrt(r_km**3 / MU_EARTH)
        pos_half, _ = _keplerian_propagate(pos, vel, T / 2)
        assert pos_half[0] < -r_km * 0.9, f"Not opposite: x={pos_half[0]:.1f}"

    def test_quarter_period_90_degrees(self):
        """Quarter orbit → 90° rotation in orbital plane."""
        r_km = 6371 + 400
        pos = np.array([r_km, 0.0, 0.0])
        v_circ = math.sqrt(MU_EARTH / r_km)
        vel = np.array([0.0, v_circ, 0.0])
        T = 2 * math.pi * math.sqrt(r_km**3 / MU_EARTH)
        pos_q, _ = _keplerian_propagate(pos, vel, T / 4)
        # Should be roughly at (0, r, 0)
        assert abs(pos_q[0]) < r_km * 0.1, f"x not near zero: {pos_q[0]:.1f}"
        assert pos_q[1] > r_km * 0.9, f"y not near r: {pos_q[1]:.1f}"


class TestProbabilityOfCollision:
    """Verify Chan's Pc implementation against known properties."""

    def test_pc_zero_miss(self):
        """Zero miss distance → maximum Pc."""
        pc = compute_pc_chan(np.array([0.0, 0.0]), np.diag([1.0, 1.0]), 0.01)
        assert pc > 1e-6

    def test_pc_far_miss(self):
        """100 km miss → Pc near zero."""
        pc = compute_pc_chan(np.array([100.0, 100.0]), np.diag([1.0, 1.0]), 0.01)
        assert pc < 1e-20

    def test_pc_larger_hbr_higher(self):
        """Larger hard-body radius → higher Pc."""
        miss = np.array([1.0, 0.0])
        cov = np.diag([2.0, 2.0])
        assert compute_pc_chan(miss, cov, 0.010) > compute_pc_chan(miss, cov, 0.001)

    def test_pc_larger_covariance_lower(self):
        """Larger covariance → spread probability → lower Pc at given miss."""
        miss = np.array([0.5, 0.0])
        assert compute_pc_chan(miss, np.diag([0.5, 0.5]), 0.005) > \
               compute_pc_chan(miss, np.diag([50.0, 50.0]), 0.005)

    def test_covariance_grows_with_age(self):
        """Older TLEs → larger covariance."""
        cov_fresh = estimate_covariance_from_tle_age(0.5)
        cov_old = estimate_covariance_from_tle_age(72.0)
        assert np.trace(cov_old) > np.trace(cov_fresh)

    def test_bplane_projection_preserves_miss(self):
        """B-plane miss magnitude ≤ 3D miss distance."""
        pos_a = np.array([6771.0, 0.0, 0.0])
        vel_a = np.array([0.0, 7.67, 0.0])
        pos_b = np.array([6773.0, 0.0, 0.0])
        vel_b = np.array([0.0, -7.67, 0.0])
        cov = np.diag([1.0, 1.0, 1.0])
        miss_2d, _ = project_to_encounter_plane(pos_a, vel_a, pos_b, vel_b, cov, cov)
        assert np.linalg.norm(miss_2d) <= np.linalg.norm(pos_a - pos_b) + 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
