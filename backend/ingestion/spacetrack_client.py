"""Space-Track.org REST API client — supplemental TLE/GP data source.

Space-Track.org is the official US Space Force public data portal.
It carries more objects than CelesTrak (~50,000 vs ~25,000) and updates
TLEs within minutes of each radar pass.

Authentication:
  - Free account at https://www.space-track.org/auth/createAccount
  - Set SPACETRACK_USER and SPACETRACK_PASSWORD environment variables
  - Uses cookie-based session login (single POST to /ajaxauth/login)

API pattern:
  - Base: https://www.space-track.org
  - Login: POST /ajaxauth/login  (form-encoded identity + password)
  - Query: GET /basicspacedata/query/class/gp/EPOCH/>now-30/orderby/NORAD_CAT_ID/format/json
  - Rate limit: 200 requests/hour (soft), 300/hour (hard)

Data flow:
  1. Login → get session cookie
  2. Query GP catalog → get JSON array of orbital elements
  3. Parse into same dict format as CelesTrak GP catalog
  4. Return to pipeline for upsert

This is an OPTIONAL upgrade. The pipeline works fine with CelesTrak alone.
Space-Track adds coverage for classified-then-declassified objects, analyst
objects, and more timely TLE updates.
"""
import logging
from datetime import datetime, timezone, timedelta

import httpx

from config import get_settings

logger = logging.getLogger("orbitpulse.ingestion.spacetrack_client")
settings = get_settings()

_BASE_URL = "https://www.space-track.org"
_LOGIN_URL = f"{_BASE_URL}/ajaxauth/login"
_TIMEOUT = httpx.Timeout(60.0, connect=15.0)


class SpaceTrackError(Exception):
    """Raised when Space-Track.org is unreachable, auth fails, or returns an error."""
    pass


async def _login(client: httpx.AsyncClient) -> None:
    """Authenticate with Space-Track.org and store the session cookie.

    Uses form-encoded POST to /ajaxauth/login. The response sets a
    session cookie that subsequent GET requests use for authorization.

    Raises:
        SpaceTrackError: If credentials are missing, invalid, or the
                         login endpoint is unreachable.
    """
    user = settings.spacetrack_user
    password = settings.spacetrack_password

    if not user or not password:
        raise SpaceTrackError(
            "Space-Track credentials not configured. "
            "Set SPACETRACK_USER and SPACETRACK_PASSWORD environment variables."
        )

    try:
        response = await client.post(
            _LOGIN_URL,
            data={"identity": user, "password": password},
        )

        if response.status_code != 200:
            raise SpaceTrackError(
                f"Space-Track login returned HTTP {response.status_code}"
            )

        # Successful login returns a JSON string "Login successful"
        body = response.text.strip().strip('"')
        if "Login" not in body:
            raise SpaceTrackError(
                f"Space-Track login rejected: {body[:200]}"
            )

        logger.info("Space-Track.org login successful")

    except httpx.HTTPError as e:
        raise SpaceTrackError(f"Space-Track login request failed: {e}") from e


async def fetch_spacetrack_gp_catalog(
    epoch_days: int = 30,
    limit: int = 50000,
) -> list[dict]:
    """Fetch the GP catalog from Space-Track.org in JSON format.

    Queries the General Perturbations (GP) class with an epoch filter
    to get only recently-updated objects. The response format matches
    CelesTrak's GP JSON closely, so we normalize field names.

    Args:
        epoch_days: Only include objects with TLE epoch within this
                    many days of now. Default 30 (covers most active objects).
        limit: Maximum number of objects to return. Default 50,000.

    Returns:
        List of GP catalog entries as dictionaries, normalized to
        CelesTrak field names for compatibility with the upsert pipeline.

    Raises:
        SpaceTrackError: If auth fails, the query fails, or rate-limited.
    """
    # Build the query URL
    # Space-Track uses a REST-path query syntax:
    #   /basicspacedata/query/class/gp/EPOCH/>now-30/orderby/NORAD_CAT_ID/format/json/limit/50000
    epoch_filter = f"now-{epoch_days}"
    query_path = (
        f"/basicspacedata/query"
        f"/class/gp"
        f"/EPOCH/%3E{epoch_filter}"
        f"/orderby/NORAD_CAT_ID"
        f"/format/json"
        f"/limit/{limit}"
    )
    query_url = f"{_BASE_URL}{query_path}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # Step 1: Login
            await _login(client)

            # Step 2: Query
            logger.info(f"Fetching Space-Track GP catalog (epoch > now-{epoch_days}d)...")
            response = await client.get(query_url)

            if response.status_code == 429:
                raise SpaceTrackError(
                    "Space-Track rate limit exceeded. "
                    "Limit: 200 requests/hour. Try again later."
                )

            if response.status_code != 200:
                raise SpaceTrackError(
                    f"Space-Track query returned HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )

            data = response.json()

            if not isinstance(data, list):
                raise SpaceTrackError(
                    f"Space-Track returned unexpected format: "
                    f"{type(data).__name__} instead of list"
                )

            # Normalize field names to match CelesTrak GP format
            normalized = _normalize_to_celestrak_format(data)

            logger.info(
                f"Fetched Space-Track GP catalog: {len(normalized)} objects "
                f"(raw: {len(data)})"
            )
            return normalized

    except httpx.HTTPError as e:
        raise SpaceTrackError(
            f"Space-Track query request failed: {e}"
        ) from e


def _normalize_to_celestrak_format(st_data: list[dict]) -> list[dict]:
    """Normalize Space-Track GP JSON to CelesTrak field names.

    Space-Track uses identical field names for most GP elements,
    but some differ. We normalize so the pipeline upsert functions
    work identically regardless of source.

    Space-Track fields → CelesTrak fields:
      NORAD_CAT_ID → NORAD_CAT_ID (same)
      OBJECT_NAME → OBJECT_NAME (same)
      OBJECT_TYPE → OBJECT_TYPE (same)
      RCS_SIZE → RCS_SIZE (same)
      COUNTRY_CODE → COUNTRY_CODE (same)
      LAUNCH_DATE → LAUNCH_DATE (same)
      DECAY_DATE → DECAY_DATE (same)
      TLE_LINE1 → TLE_LINE1 (same)
      TLE_LINE2 → TLE_LINE2 (same)
    """
    normalized: list[dict] = []
    for entry in st_data:
        norad_id = entry.get("NORAD_CAT_ID")
        if norad_id is None:
            continue

        normalized.append({
            "NORAD_CAT_ID": norad_id,
            "OBJECT_NAME": entry.get("OBJECT_NAME", f"UNKNOWN-{norad_id}"),
            "OBJECT_TYPE": entry.get("OBJECT_TYPE"),
            "RCS_SIZE": entry.get("RCS_SIZE"),
            "COUNTRY_CODE": entry.get("COUNTRY_CODE"),
            "LAUNCH_DATE": entry.get("LAUNCH_DATE"),
            "DECAY_DATE": entry.get("DECAY_DATE"),
            "TLE_LINE1": entry.get("TLE_LINE1", ""),
            "TLE_LINE2": entry.get("TLE_LINE2", ""),
            "_DATA_SOURCE": "space-track",  # Tag for provenance
        })

    return normalized


async def fetch_supplemental_objects(
    norad_ids: list[int],
) -> list[dict]:
    """Fetch specific objects from Space-Track by NORAD ID.

    Useful for getting TLEs for objects not in CelesTrak's active catalog,
    such as recently-launched objects or analyst objects.

    Args:
        norad_ids: List of NORAD catalog IDs to fetch.

    Returns:
        List of GP entries (normalized to CelesTrak format).

    Raises:
        SpaceTrackError: If auth or query fails.
    """
    if not norad_ids:
        return []

    # Space-Track allows comma-separated NORAD IDs in the query
    ids_str = ",".join(str(nid) for nid in norad_ids[:100])  # Max 100 per query
    query_path = (
        f"/basicspacedata/query"
        f"/class/gp"
        f"/NORAD_CAT_ID/{ids_str}"
        f"/format/json"
    )
    query_url = f"{_BASE_URL}{query_path}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            await _login(client)

            response = await client.get(query_url)
            if response.status_code != 200:
                raise SpaceTrackError(
                    f"Space-Track supplemental query returned HTTP {response.status_code}"
                )

            data = response.json()
            if not isinstance(data, list):
                return []

            return _normalize_to_celestrak_format(data)

    except httpx.HTTPError as e:
        raise SpaceTrackError(
            f"Space-Track supplemental query failed: {e}"
        ) from e
""",
<parameter name="toolAction">Creating Space-Track client
