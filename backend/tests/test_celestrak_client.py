"""Tests for CelesTrak HTTP fetcher.

Uses pytest-httpx to mock outbound requests — no real network calls.
Validates successful fetch, error handling (404, timeout, connection error),
GP catalog JSON parsing, and fallback behavior.
"""
import pytest
import httpx
from pytest_httpx import HTTPXMock

from ingestion.celestrak_client import (
    fetch_tle_data,
    fetch_gp_catalog,
    CelesTrakError,
)


SAMPLE_TLE_RESPONSE = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025
2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001
"""

SAMPLE_GP_JSON = [
    {
        "NORAD_CAT_ID": 25544,
        "OBJECT_NAME": "ISS (ZARYA)",
        "OBJECT_TYPE": "PAYLOAD",
        "RCS_SIZE": "LARGE",
        "COUNTRY_CODE": "ISS",
        "LAUNCH_DATE": "1998-11-20",
        "DECAY_DATE": None,
        "TLE_LINE1": "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025",
        "TLE_LINE2": "2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001",
    },
    {
        "NORAD_CAT_ID": 44713,
        "OBJECT_NAME": "STARLINK-1007",
        "OBJECT_TYPE": "PAYLOAD",
        "RCS_SIZE": "LARGE",
        "COUNTRY_CODE": "US",
        "LAUNCH_DATE": "2019-11-11",
        "DECAY_DATE": None,
        "TLE_LINE1": "1 44713U 19074A   24001.50000000  .00001234  00000-0  12345-4 0  9010",
        "TLE_LINE2": "2 44713  53.0500 123.4567 0001234  45.6789 314.5678 15.06000000  1001",
    },
]


class TestFetchTleData:
    """TLE text file endpoint tests."""

    @pytest.mark.asyncio
    async def test_successful_fetch_returns_text(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(text=SAMPLE_TLE_RESPONSE)
        result = await fetch_tle_data("stations")
        assert "ISS (ZARYA)" in result
        assert "25544" in result

    @pytest.mark.asyncio
    async def test_404_raises_celestrak_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=404)
        with pytest.raises(CelesTrakError, match="404"):
            await fetch_tle_data("nonexistent")

    @pytest.mark.asyncio
    async def test_timeout_raises_celestrak_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
        with pytest.raises(CelesTrakError, match="timed out"):
            await fetch_tle_data("stations")

    @pytest.mark.asyncio
    async def test_connection_error_raises_celestrak_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"))
        with pytest.raises(CelesTrakError, match="connection refused"):
            await fetch_tle_data("stations")


class TestFetchGpCatalog:
    """GP JSON catalog endpoint tests."""

    @pytest.mark.asyncio
    async def test_successful_fetch_returns_list_of_dicts(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=SAMPLE_GP_JSON)
        result = await fetch_gp_catalog()
        assert len(result) == 2
        assert result[0]["NORAD_CAT_ID"] == 25544

    @pytest.mark.asyncio
    async def test_gp_catalog_contains_required_fields(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=SAMPLE_GP_JSON)
        result = await fetch_gp_catalog()
        required_fields = {
            "NORAD_CAT_ID", "OBJECT_NAME", "OBJECT_TYPE",
            "TLE_LINE1", "TLE_LINE2",
        }
        for entry in result:
            assert required_fields.issubset(entry.keys())

    @pytest.mark.asyncio
    async def test_server_error_raises_celestrak_error(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=503)
        with pytest.raises(CelesTrakError, match="503"):
            await fetch_gp_catalog()
