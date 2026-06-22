"""Tests for risk scoring and triage tier assignment.

Validates the weighted formula behavior, trend multiplier effect,
hard-override rules, and boundary conditions for all three tiers.
"""
import pytest
from core.risk_scoring import compute_risk_score, assign_tier
from db.models import TriageTier


class TestComputeRiskScore:
    """Risk score formula validation."""

    def test_close_fast_large_scores_high(self):
        """0.1 km miss, 10 km/s, two LARGE objects → near 1.0."""
        score = compute_risk_score(0.1, 10.0, "LARGE", "LARGE", None)
        assert score >= 0.8

    def test_far_slow_small_scores_low(self):
        """9.0 km miss, 1 km/s, two SMALL objects → near 0.0."""
        score = compute_risk_score(9.0, 1.0, "SMALL", "SMALL", None)
        assert score <= 0.3

    def test_score_always_in_zero_one_range(self):
        for miss in [0.01, 0.5, 1.0, 5.0, 10.0]:
            for vel in [0.1, 5.0, 15.0]:
                for size in ["SMALL", "MEDIUM", "LARGE", None]:
                    score = compute_risk_score(miss, vel, size, size, None)
                    assert 0.0 <= score <= 1.0, f"Score {score} out of range"

    def test_smaller_distance_gives_higher_score(self):
        close = compute_risk_score(0.5, 5.0, "MEDIUM", "MEDIUM", None)
        far = compute_risk_score(5.0, 5.0, "MEDIUM", "MEDIUM", None)
        assert close > far

    def test_higher_velocity_gives_higher_score(self):
        fast = compute_risk_score(2.0, 12.0, "MEDIUM", "MEDIUM", None)
        slow = compute_risk_score(2.0, 2.0, "MEDIUM", "MEDIUM", None)
        assert fast > slow

    def test_larger_size_gives_higher_score(self):
        large = compute_risk_score(2.0, 5.0, "LARGE", "LARGE", None)
        small = compute_risk_score(2.0, 5.0, "SMALL", "SMALL", None)
        assert large > small

    def test_converging_trend_amplifies_score(self):
        """Miss decreased from 5.0 to 2.0 → trend = 1.3."""
        converging = compute_risk_score(2.0, 5.0, "MEDIUM", "MEDIUM", 5.0)
        no_trend = compute_risk_score(2.0, 5.0, "MEDIUM", "MEDIUM", None)
        assert converging > no_trend

    def test_diverging_trend_attenuates_score(self):
        """Miss increased from 1.0 to 3.0 → trend = 0.7."""
        diverging = compute_risk_score(3.0, 5.0, "MEDIUM", "MEDIUM", 1.0)
        no_trend = compute_risk_score(3.0, 5.0, "MEDIUM", "MEDIUM", None)
        assert diverging < no_trend

    def test_trend_is_multiplicative_not_additive(self):
        """A distant conjunction with converging trend should not become ACTION."""
        score = compute_risk_score(8.0, 1.0, "SMALL", "SMALL", 9.0)
        assert score < 0.7, (
            f"Score {score} is too high — trend should not inflate a distant "
            f"low-velocity conjunction to ACTION threshold"
        )

    def test_none_sizes_use_default_factor(self):
        """Missing size data should not crash — uses 0.5 default."""
        score = compute_risk_score(2.0, 5.0, None, None, None)
        assert 0.0 <= score <= 1.0


class TestAssignTier:
    """Triage tier assignment validation."""

    def test_high_risk_is_action(self):
        tier = assign_tier(0.8, 2.0, 5.0)
        assert tier == TriageTier.ACTION

    def test_medium_risk_close_is_watchlist(self):
        tier = assign_tier(0.4, 3.0, 3.0)
        assert tier == TriageTier.WATCHLIST

    def test_low_risk_is_dismissed(self):
        tier = assign_tier(0.1, 8.0, 2.0)
        assert tier == TriageTier.DISMISSED

    def test_hard_override_close_fast_always_action(self):
        """Sub-1km, >5 km/s is always ACTION regardless of risk score."""
        tier = assign_tier(0.2, 0.5, 8.0)
        assert tier == TriageTier.ACTION

    def test_medium_risk_but_far_is_dismissed(self):
        """Risk >= 0.3 but miss > 5 km → DISMISSED (not WATCHLIST)."""
        tier = assign_tier(0.4, 7.0, 3.0)
        assert tier == TriageTier.DISMISSED

    def test_exactly_at_action_threshold(self):
        tier = assign_tier(0.7, 2.0, 5.0)
        assert tier == TriageTier.ACTION

    def test_exactly_at_watchlist_threshold(self):
        tier = assign_tier(0.3, 4.0, 3.0)
        assert tier == TriageTier.WATCHLIST
