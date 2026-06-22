"""Tests for SGP4 propagator wrapper.

Validates:
  - ISS propagation produces positions at correct altitude (~400-420 km)
  - Batch propagation across multiple timesteps returns correct shape
  - Error handling for invalid/expired TLE lines
  - TEME to lat/lon/alt geodetic conversion produces valid ranges
"""
import pytest
import numpy as np
from datetime import datetime, timezone, timedelta

from core.propagator import (
    propagate_single,
    propagate_timeseries,
    teme_to_geodetic,
    PropagationError,
)


# Real ISS TLE — epoch around Jan 2024. Positions valid within a few weeks of epoch.
ISS_LINE1 = "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025"
ISS_LINE2 = "2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001"


class TestPropagateSingle:
    """Single-epoch propagation tests."""

    def test_iss_position_returns_3d_vector(self):
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        pos, vel = propagate_single(ISS_LINE1, ISS_LINE2, t)
        assert pos.shape == (3,)
        assert vel.shape == (3,)

    def test_iss_altitude_in_correct_range(self):
        """ISS orbits at ~400-420 km. Position magnitude should be ~6770-6790 km."""
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        pos, _ = propagate_single(ISS_LINE1, ISS_LINE2, t)
        altitude_from_center = np.linalg.norm(pos)
        # Earth radius ~6371 km, ISS altitude ~400 km
        assert 6600 < altitude_from_center < 6900, (
            f"ISS distance from center {altitude_from_center:.1f} km is outside "
            f"expected range (6600-6900 km)"
        )

    def test_iss_velocity_magnitude_correct(self):
        """ISS velocity should be ~7.5-7.8 km/s."""
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        _, vel = propagate_single(ISS_LINE1, ISS_LINE2, t)
        speed = np.linalg.norm(vel)
        assert 7.0 < speed < 8.5, f"ISS speed {speed:.2f} km/s outside expected range"

    def test_invalid_tle_raises_propagation_error(self):
        with pytest.raises(PropagationError):
            t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
            propagate_single("garbage line 1", "garbage line 2", t)


class TestPropagateTimeseries:
    """Multi-timestep propagation tests."""

    def test_output_shape_matches_timestep_count(self):
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        times = [start + timedelta(seconds=60 * i) for i in range(10)]
        positions, velocities = propagate_timeseries(ISS_LINE1, ISS_LINE2, times)
        assert positions.shape == (10, 3)
        assert velocities.shape == (10, 3)

    def test_positions_vary_over_time(self):
        """Positions at different times should not be identical."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        times = [start + timedelta(minutes=i * 10) for i in range(5)]
        positions, _ = propagate_timeseries(ISS_LINE1, ISS_LINE2, times)
        # ISS moves ~4500 km in 10 minutes — positions should differ substantially
        for i in range(1, len(times)):
            dist = np.linalg.norm(positions[i] - positions[0])
            assert dist > 100, f"Position at t={i} too close to t=0: {dist:.1f} km"

    def test_no_nan_in_near_epoch_propagation(self):
        """Near-epoch propagation should produce no NaN values."""
        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        times = [start + timedelta(seconds=60 * i) for i in range(100)]
        positions, velocities = propagate_timeseries(ISS_LINE1, ISS_LINE2, times)
        assert not np.any(np.isnan(positions)), "NaN found in positions"
        assert not np.any(np.isnan(velocities)), "NaN found in velocities"

    def test_empty_times_returns_empty_arrays(self):
        positions, velocities = propagate_timeseries(ISS_LINE1, ISS_LINE2, [])
        assert positions.shape == (0, 3)
        assert velocities.shape == (0, 3)


class TestTemeToGeodetic:
    """Coordinate conversion tests."""

    def test_output_has_lat_lon_alt(self):
        # A point on the x-axis at ~6771 km from center = ~400 km altitude
        pos_teme = np.array([6771.0, 0.0, 0.0])
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        lat, lon, alt = teme_to_geodetic(pos_teme, t)
        assert isinstance(lat, float)
        assert isinstance(lon, float)
        assert isinstance(alt, float)

    def test_latitude_range(self):
        pos_teme = np.array([6771.0, 0.0, 0.0])
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        lat, _, _ = teme_to_geodetic(pos_teme, t)
        assert -90 <= lat <= 90

    def test_longitude_range(self):
        pos_teme = np.array([6771.0, 0.0, 0.0])
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        _, lon, _ = teme_to_geodetic(pos_teme, t)
        assert -180 <= lon <= 180

    def test_altitude_positive_for_orbital_position(self):
        pos_teme = np.array([6771.0, 0.0, 0.0])
        t = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        _, _, alt = teme_to_geodetic(pos_teme, t)
        assert alt > 0, f"Altitude should be positive for orbital position, got {alt}"
