"""Schema models for space objects, ISS tracking, and position data."""
from pydantic import BaseModel


class CatalogObject(BaseModel):
    """Single entry in the satellite catalog — sent to frontend for globe labeling."""
    norad_id: int
    name: str
    object_type: str
    rcs_size: str | None
    country_code: str | None

    model_config = {"from_attributes": True}


class ISSPosition(BaseModel):
    """Real-time ISS position with TLE validation status.

    The 'validated' field indicates whether SGP4 propagation completed
    without errors — it is a self-consistency check, not an external validation.
    """
    lat: float
    lon: float
    alt_km: float
    validated: bool
    tle_epoch: str
    timestamp: str


class PositionUpdate(BaseModel):
    """Flat array format for WebSocket position broadcasts.

    Each inner list is [norad_id, latitude, longitude, altitude_km].
    Flat arrays save ~60% bandwidth vs nested objects for 5000+ objects.
    """
    positions: list[list[float]]
