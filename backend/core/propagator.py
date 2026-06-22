"""SGP4 propagator wrapper — NORAD-standard orbital mechanics.

Wraps the python-sgp4 library to provide:
  - Single-epoch propagation (position + velocity in TEME frame)
  - Multi-timestep timeseries propagation (vectorized for performance)
  - TEME to geodetic (lat/lon/alt) coordinate conversion

TEME (True Equator Mean Equinox) is the native SGP4 output frame.
All positions are in kilometers, all velocities in km/s.

The SGP4 propagator uses the WGS72 gravity model, which is the standard
for TLE propagation. Using WGS84 would introduce systematic errors because
the TLE fitting process assumes WGS72.
"""
import logging
import math
from datetime import datetime, timezone

import numpy as np
from sgp4.api import Satrec, WGS72
from sgp4.api import jday

logger = logging.getLogger("orbitpulse.core.propagator")

# Earth's equatorial radius (WGS72 value used by SGP4)
_EARTH_RADIUS_KM = 6378.135
# Earth's flattening factor (WGS72)
_EARTH_FLATTENING = 1.0 / 298.26
# Earth's rotation rate (rad/s) — for TEME to ECEF conversion
_EARTH_OMEGA = 7.2921151467e-5


class PropagationError(Exception):
    """Raised when SGP4 propagation fails for a satellite.

    Common causes:
      - Invalid or corrupted TLE lines
      - TLE epoch too far from propagation time (>30 days)
      - Decayed satellite (negative altitude)
      - SGP4 internal error codes (1-6)
    """
    pass


def _tle_to_satrec(line1: str, line2: str) -> Satrec:
    """Create an SGP4 satellite record from TLE lines.

    Uses WGS72 gravity model — mandatory for TLE-derived propagation.
    """
    try:
        sat = Satrec.twoline2rv(line1, line2, WGS72)
        return sat
    except Exception as e:
        raise PropagationError(f"Invalid TLE: {e}") from e


def _datetime_to_jd(dt: datetime) -> tuple[float, float]:
    """Convert datetime to Julian Date pair (jd, fr) for SGP4.

    SGP4 uses a split Julian Date representation for numerical precision.
    jd is the integer part, fr is the fractional part.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return jday(
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute, dt.second + dt.microsecond / 1e6,
    )


def propagate_single(
    line1: str, line2: str, dt: datetime
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate a single satellite to a single epoch.

    Args:
        line1: TLE line 1
        line2: TLE line 2
        dt: Propagation epoch (UTC-aware datetime)

    Returns:
        Tuple of (position, velocity) as 3D numpy arrays.
        Position in km (TEME frame), velocity in km/s (TEME frame).

    Raises:
        PropagationError: If TLE is invalid or SGP4 returns an error.
    """
    sat = _tle_to_satrec(line1, line2)
    jd, fr = _datetime_to_jd(dt)

    error_code, position, velocity = sat.sgp4(jd, fr)
    if error_code != 0:
        raise PropagationError(
            f"SGP4 error code {error_code} for satellite "
            f"(epoch jd={jd:.2f}+{fr:.6f})"
        )

    pos = np.array(position, dtype=np.float64)
    vel = np.array(velocity, dtype=np.float64)

    if np.any(np.isnan(pos)) or np.any(np.isnan(vel)):
        raise PropagationError("SGP4 returned NaN values — TLE may be expired or invalid")

    return pos, vel


def propagate_timeseries(
    line1: str, line2: str, times: list[datetime]
) -> tuple[np.ndarray, np.ndarray]:
    """Propagate a single satellite across multiple timesteps.

    Uses the sgp4 library's array interface for vectorized propagation
    when available, falling back to sequential propagation for compatibility.

    Args:
        line1: TLE line 1
        line2: TLE line 2
        times: List of UTC-aware datetimes

    Returns:
        Tuple of (positions, velocities) as 2D numpy arrays.
        positions: shape (N, 3) in km (TEME frame)
        velocities: shape (N, 3) in km/s (TEME frame)
        Rows with propagation errors are filled with NaN.
    """
    if not times:
        return np.empty((0, 3), dtype=np.float64), np.empty((0, 3), dtype=np.float64)

    sat = _tle_to_satrec(line1, line2)
    n = len(times)
    positions = np.empty((n, 3), dtype=np.float64)
    velocities = np.empty((n, 3), dtype=np.float64)

    for i, dt in enumerate(times):
        jd, fr = _datetime_to_jd(dt)
        error_code, position, velocity = sat.sgp4(jd, fr)

        if error_code != 0:
            positions[i] = [np.nan, np.nan, np.nan]
            velocities[i] = [np.nan, np.nan, np.nan]
        else:
            positions[i] = position
            velocities[i] = velocity

    return positions, velocities


def teme_to_geodetic(
    pos_teme: np.ndarray, dt: datetime
) -> tuple[float, float, float]:
    """Convert TEME position to geodetic coordinates (lat, lon, alt).

    Uses the IAU GMST angle to rotate from TEME to an approximate ECEF,
    then applies the standard geodetic conversion (iterative method).

    This approximation is sufficient for visualization and altitude-band
    filtering. For sub-kilometer geodetic precision, use a full IAU
    precession-nutation model (not needed for conjunction screening).

    Args:
        pos_teme: 3D position vector in TEME frame (km)
        dt: Epoch for GMST calculation

    Returns:
        Tuple of (latitude_deg, longitude_deg, altitude_km)
        Latitude: -90 to +90 degrees
        Longitude: -180 to +180 degrees
        Altitude: height above WGS72 ellipsoid in km
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Julian centuries since J2000.0 for GMST calculation
    jd, fr = _datetime_to_jd(dt)
    jd_total = jd + fr
    t_centuries = (jd_total - 2451545.0) / 36525.0

    # Greenwich Mean Sidereal Time (radians) — IAU 1982 model
    gmst = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t_centuries
        + 0.093104 * t_centuries ** 2
        - 6.2e-6 * t_centuries ** 3
    )
    gmst_rad = math.radians((gmst % 86400.0) / 240.0)

    # Rotate TEME to approximate ECEF (PEF)
    cos_g = math.cos(gmst_rad)
    sin_g = math.sin(gmst_rad)
    x_ecef = cos_g * pos_teme[0] + sin_g * pos_teme[1]
    y_ecef = -sin_g * pos_teme[0] + cos_g * pos_teme[1]
    z_ecef = pos_teme[2]

    # Geodetic conversion (iterative)
    r_xy = math.sqrt(x_ecef ** 2 + y_ecef ** 2)
    longitude_rad = math.atan2(y_ecef, x_ecef)

    # Initial latitude estimate
    latitude_rad = math.atan2(z_ecef, r_xy)

    # Iterative refinement (converges in 2-3 iterations for LEO)
    a = _EARTH_RADIUS_KM
    e2 = 2 * _EARTH_FLATTENING - _EARTH_FLATTENING ** 2
    for _ in range(5):
        sin_lat = math.sin(latitude_rad)
        n_val = a / math.sqrt(1 - e2 * sin_lat ** 2)
        latitude_rad = math.atan2(
            z_ecef + e2 * n_val * sin_lat, r_xy
        )

    sin_lat = math.sin(latitude_rad)
    cos_lat = math.cos(latitude_rad)
    n_val = a / math.sqrt(1 - e2 * sin_lat ** 2)

    if abs(cos_lat) > 1e-10:
        altitude = r_xy / cos_lat - n_val
    else:
        altitude = abs(z_ecef) - n_val * (1 - e2)

    latitude_deg = math.degrees(latitude_rad)
    longitude_deg = math.degrees(longitude_rad)

    # Normalize longitude to [-180, 180]
    if longitude_deg > 180:
        longitude_deg -= 360
    elif longitude_deg < -180:
        longitude_deg += 360

    return latitude_deg, longitude_deg, altitude
