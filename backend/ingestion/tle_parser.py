"""Three-line TLE (Two-Line Element) set parser.

CelesTrak serves TLE data in the standard 3-line format:
  Line 0: Satellite name (up to 24 chars)
  Line 1: Orbital elements part 1 (starts with '1')
  Line 2: Orbital elements part 2 (starts with '2')

This parser extracts satellite name, NORAD catalog ID, raw TLE lines
(for SGP4 consumption), and epoch datetime from the TLE text.

Malformed entries are silently skipped with warning-level logging
because CelesTrak occasionally serves corrupted TLE sets.
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("orbitpulse.ingestion.tle_parser")

# TLE line validation patterns — loose enough to accept real-world formatting
# variations but strict enough to reject garbage
_LINE1_PATTERN = re.compile(r"^1\s+\d{1,5}")
_LINE2_PATTERN = re.compile(r"^2\s+\d{1,5}")


@dataclass(frozen=True)
class ParsedTLE:
    """Immutable parsed TLE record.

    Fields:
        name: Satellite name from line 0
        norad_id: NORAD catalog number (5-digit integer)
        line1: Raw TLE line 1 (for SGP4 propagation)
        line2: Raw TLE line 2 (for SGP4 propagation)
        epoch: TLE epoch as UTC-aware datetime
    """
    name: str
    norad_id: int
    line1: str
    line2: str
    epoch: datetime


def _parse_epoch(line1: str) -> datetime:
    """Convert TLE epoch field (columns 18-32 of line 1) to UTC datetime.

    Format: YYDDD.DDDDDDDD
      YY = two-digit year (00-56 → 2000-2056, 57-99 → 1957-1999)
      DDD.DDDDDDDD = fractional day of year

    The year boundary at 57 is the TLE standard convention matching the
    launch of Sputnik 1. NORAD will likely update this before 2057.
    """
    epoch_str = line1[18:32].strip()
    year_2d = int(epoch_str[:2])
    day_frac = float(epoch_str[2:])

    year = 2000 + year_2d if year_2d < 57 else 1900 + year_2d

    # Day 1 = January 1, so subtract 1 from the integer part
    # and add the fractional day as timedelta
    jan1 = datetime(year, 1, 1, tzinfo=timezone.utc)
    epoch = jan1 + timedelta(days=day_frac - 1)

    return epoch


def _extract_norad_id(tle_line: str) -> int | None:
    """Extract NORAD ID from columns 2-7 of a TLE line.

    Returns None if the field is not a valid integer (malformed line).
    """
    try:
        # NORAD ID is in columns 2-7, followed by classification letter
        raw = tle_line[2:7].strip()
        return int(raw)
    except (ValueError, IndexError):
        return None


def parse_tle_text(text: str) -> list[ParsedTLE]:
    """Parse raw TLE text into structured records.

    Expects the standard 3-line format where each TLE set is:
      name_line (any text not starting with '1' or '2')
      line1 (starts with '1')
      line2 (starts with '2')

    Lines are grouped into triplets. If a line 0 (name) is missing,
    the pair is still attempted with an empty name. If line1 and line2
    NORAD IDs don't match, the entry is skipped.

    Malformed entries produce a warning log but never raise exceptions.
    This is necessary because CelesTrak data occasionally contains
    encoding errors or truncated lines.

    Args:
        text: Raw TLE text from CelesTrak (may contain thousands of entries)

    Returns:
        List of successfully parsed TLE records, in order of appearance
    """
    if not text or not text.strip():
        return []

    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    results: list[ParsedTLE] = []
    idx = 0

    while idx < len(lines):
        # Look for a line1 (starts with '1')
        if _LINE1_PATTERN.match(lines[idx]):
            # No name line — line1 is at current position
            name = ""
            line1 = lines[idx]
            idx += 1
        elif idx + 1 < len(lines) and _LINE1_PATTERN.match(lines[idx + 1]):
            # Current line is the name, next line is line1
            name = lines[idx].strip()
            line1 = lines[idx + 1]
            idx += 2
        else:
            # Neither pattern matches — skip this line
            idx += 1
            continue

        # Expect line2 immediately after line1
        if idx >= len(lines) or not _LINE2_PATTERN.match(lines[idx]):
            logger.warning(f"Missing line2 after line1 for '{name}' — skipping")
            continue

        line2 = lines[idx]
        idx += 1

        # Validate NORAD ID consistency between line1 and line2
        norad_1 = _extract_norad_id(line1)
        norad_2 = _extract_norad_id(line2)

        if norad_1 is None or norad_2 is None:
            logger.warning(f"Cannot extract NORAD ID from TLE for '{name}' — skipping")
            continue

        if norad_1 != norad_2:
            logger.warning(
                f"NORAD ID mismatch in TLE for '{name}': "
                f"line1={norad_1}, line2={norad_2} — skipping"
            )
            continue

        # Parse epoch from line1
        try:
            epoch = _parse_epoch(line1)
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse epoch for '{name}' (NORAD {norad_1}): {e}")
            continue

        results.append(ParsedTLE(
            name=name,
            norad_id=norad_1,
            line1=line1,
            line2=line2,
            epoch=epoch,
        ))

    if results:
        logger.info(f"Parsed {len(results)} TLE records from {len(lines)} lines")
    else:
        logger.warning("No valid TLE records found in input text")

    return results
