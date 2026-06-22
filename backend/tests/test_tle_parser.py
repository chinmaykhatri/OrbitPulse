"""Tests for TLE three-line format parser.

Validates parsing of standard 3-line TLE format (name + line1 + line2),
NORAD ID extraction, epoch conversion, and handling of edge cases
(empty input, malformed data, duplicate NORAD IDs, missing lines).
"""
import pytest
from datetime import timezone

from ingestion.tle_parser import parse_tle_text, ParsedTLE


# Real ISS TLE — structurally valid, used across multiple tests
SAMPLE_TLE_TEXT = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025
2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001
STARLINK-1007
1 44713U 19074A   24001.50000000  .00001234  00000-0  12345-4 0  9010
2 44713  53.0500 123.4567 0001234  45.6789 314.5678 15.06000000  1001"""


class TestParseTleText:
    """Core parsing — happy path and structural validation."""

    def test_parses_correct_count(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert len(results) == 2

    def test_extracts_satellite_names(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert results[0].name == "ISS (ZARYA)"
        assert results[1].name == "STARLINK-1007"

    def test_extracts_norad_ids(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert results[0].norad_id == 25544
        assert results[1].norad_id == 44713

    def test_stores_raw_tle_lines(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert results[0].line1.startswith("1 25544")
        assert results[0].line2.startswith("2 25544")
        assert results[1].line1.startswith("1 44713")
        assert results[1].line2.startswith("2 44713")

    def test_extracts_epoch_as_utc_datetime(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        epoch = results[0].epoch
        assert epoch.tzinfo == timezone.utc
        assert epoch.year == 2024
        assert epoch.month == 1

    def test_returns_parsedtle_dataclass(self):
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert isinstance(results[0], ParsedTLE)


class TestEdgeCases:
    """Malformed input, empty data, and boundary conditions."""

    def test_empty_string_returns_empty_list(self):
        assert parse_tle_text("") == []

    def test_whitespace_only_returns_empty_list(self):
        assert parse_tle_text("   \n  \n  ") == []

    def test_malformed_lines_skipped_silently(self):
        results = parse_tle_text("not a tle\njust some text\nrandom garbage")
        assert len(results) == 0

    def test_partial_tle_missing_line2_skipped(self):
        partial = "ISS (ZARYA)\n1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025\n"
        results = parse_tle_text(partial)
        assert len(results) == 0

    def test_norad_id_mismatch_between_lines_skipped(self):
        """Line1 says 25544, line2 says 99999 — should be rejected."""
        bad_tle = """TEST SAT
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025
2 99999  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001"""
        results = parse_tle_text(bad_tle)
        assert len(results) == 0

    def test_mixed_valid_and_invalid_parses_valid_only(self):
        mixed = """ISS (ZARYA)
1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025
2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001
GARBAGE LINE
NOT A TLE
ALSO NOT A TLE
STARLINK-1007
1 44713U 19074A   24001.50000000  .00001234  00000-0  12345-4 0  9010
2 44713  53.0500 123.4567 0001234  45.6789 314.5678 15.06000000  1001"""
        results = parse_tle_text(mixed)
        assert len(results) == 2

    def test_handles_windows_line_endings(self):
        windows_tle = "ISS (ZARYA)\r\n1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9025\r\n2 25544  51.6400 208.9163 0006703 311.8012 175.4507 15.50000000  5001\r\n"
        results = parse_tle_text(windows_tle)
        assert len(results) == 1
        assert results[0].norad_id == 25544


class TestEpochConversion:
    """TLE epoch field parsing — the YYDDD.dddddddd format."""

    def test_year_2000_plus_range(self):
        """Years 00-56 map to 2000-2056."""
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        assert results[0].epoch.year == 2024

    def test_epoch_day_fraction_produces_correct_month(self):
        """Day 1.5 = January 1 at noon UTC."""
        results = parse_tle_text(SAMPLE_TLE_TEXT)
        epoch = results[0].epoch
        assert epoch.month == 1
        assert epoch.day == 1
