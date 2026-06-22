"""CelesTrak HTTP client — fetches TLE data and GP catalogs.

CelesTrak is the primary data source for satellite orbital elements.
Two endpoints are used:
  1. TLE text files: /NORAD/elements/gp.php?GROUP={group}&FORMAT=tle
  2. GP JSON catalog: /NORAD/elements/gp.php?GROUP=active&FORMAT=json

The GP JSON catalog is preferred because it includes metadata (object type,
RCS size, country code, launch/decay dates) alongside the TLE lines.
The TLE text endpoint is a fallback for specific satellite groups.

All requests use httpx.AsyncClient with a 30-second timeout.
Errors are wrapped in CelesTrakError with context about what failed.
"""
import logging

import httpx

from config import get_settings

logger = logging.getLogger("orbitpulse.ingestion.celestrak_client")
settings = get_settings()

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CelesTrakError(Exception):
    """Raised when CelesTrak is unreachable or returns an error.

    Contains the original error message for upstream logging.
    The pipeline catches this and falls back to cached data when available.
    """
    pass


async def fetch_tle_data(group: str = "active") -> str:
    """Fetch raw TLE text for a satellite group.

    Args:
        group: CelesTrak group name (e.g., 'active', 'stations', 'starlink').
               'active' returns the full active satellite catalog (~25,000 entries).

    Returns:
        Raw TLE text in 3-line format.

    Raises:
        CelesTrakError: If the request fails (network error, HTTP error, timeout).
    """
    url = f"{settings.celestrak_base_url}/NORAD/elements/gp.php"
    params = {"GROUP": group, "FORMAT": "tle"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                raise CelesTrakError(
                    f"CelesTrak returned HTTP {response.status_code} "
                    f"for group '{group}'"
                )

            text = response.text
            if not text.strip():
                raise CelesTrakError(
                    f"CelesTrak returned empty response for group '{group}'"
                )

            logger.info(
                f"Fetched TLE data for group '{group}': "
                f"{len(text)} bytes"
            )
            return text

    except httpx.HTTPError as e:
        raise CelesTrakError(
            f"CelesTrak request failed for group '{group}': {e}"
        ) from e


async def fetch_gp_catalog(group: str = "active") -> list[dict]:
    """Fetch the GP catalog in JSON format — includes metadata.

    The GP JSON format provides richer data than raw TLE text:
    - NORAD_CAT_ID, OBJECT_NAME, OBJECT_TYPE, RCS_SIZE
    - COUNTRY_CODE, LAUNCH_DATE, DECAY_DATE
    - TLE_LINE1, TLE_LINE2 (same orbital elements as TLE text)

    This is the preferred ingestion source because it populates both
    the SpaceObject table (metadata) and provides TLE lines for propagation.

    Args:
        group: CelesTrak group name. 'active' returns the full catalog.

    Returns:
        List of GP catalog entries as dictionaries.

    Raises:
        CelesTrakError: If the request fails or returns non-JSON data.
    """
    url = f"{settings.celestrak_base_url}/NORAD/elements/gp.php"
    params = {"GROUP": group, "FORMAT": "json"}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)

            if response.status_code != 200:
                raise CelesTrakError(
                    f"CelesTrak GP catalog returned HTTP {response.status_code} "
                    f"for group '{group}'"
                )

            data = response.json()

            if not isinstance(data, list):
                raise CelesTrakError(
                    f"CelesTrak GP catalog returned unexpected format: "
                    f"{type(data).__name__} instead of list"
                )

            logger.info(
                f"Fetched GP catalog for group '{group}': "
                f"{len(data)} objects"
            )
            return data

    except httpx.HTTPError as e:
        raise CelesTrakError(
            f"CelesTrak GP catalog request failed for group '{group}': {e}"
        ) from e
