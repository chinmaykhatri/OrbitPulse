"""SOCRATES validation — cross-check OrbitPulse predictions against CelesTrak/SOCRATES.

SOCRATES (Satellite Orbital Conjunction Reports Assessing Threatening
Encounters in Space) is operated by CelesTrak and provides independent
conjunction assessments.

This module:
  1. Fetches the SOCRATES CSV from CelesTrak (top 10 closest approaches)
  2. Parses into structured conjunction records
  3. Matches our predictions against SOCRATES predictions
  4. Computes the delta between our miss distance and SOCRATES miss distance
  5. Generates a validation report

The validation is NOT used for decision-making. It's a confidence check
that our SGP4 propagation and conjunction detection are producing results
consistent with an independent system. Operators can view this on the
dashboard to assess system trustworthiness.
"""
import csv
import io
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select

from config import get_settings
from db.session import AsyncSessionLocal
from db.models import Conjunction
from schemas.conjunctions import SOCRATESMatch, SOCRATESValidation

logger = logging.getLogger("orbitpulse.core.socrates")
settings = get_settings()

# SOCRATES CSV endpoint — top-10 closest approaches over next 7 days
SOCRATES_URL = f"{settings.celestrak_base_url}/SOCRATES/sort-minRange.csv"

# Timeout for SOCRATES fetch
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


async def fetch_socrates_csv() -> str:
    """Fetch the SOCRATES CSV from CelesTrak.

    Returns raw CSV text. Raises on HTTP errors.
    """
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(SOCRATES_URL)
            if response.status_code != 200:
                logger.error(f"SOCRATES returned HTTP {response.status_code}")
                return ""
            text = response.text
            if not text.strip():
                logger.warning("SOCRATES returned empty response")
                return ""
            logger.info(f"Fetched SOCRATES CSV: {len(text)} bytes")
            return text
    except httpx.HTTPError as e:
        logger.error(f"SOCRATES fetch failed: {e}")
        return ""


def parse_socrates_csv(csv_text: str) -> list[dict]:
    """Parse SOCRATES CSV into structured records.

    SOCRATES CSV columns vary but typically include:
      NORAD_CAT_ID_1, NORAD_CAT_ID_2, TCA, MIN_RNG (km), REL_VEL (km/s),
      OBJECT_NAME_1, OBJECT_NAME_2

    We extract the essential fields and normalize the format.
    Returns empty list if the CSV is empty or unparseable.
    """
    if not csv_text.strip():
        return []

    records: list[dict] = []
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            try:
                norad_1 = int(row.get("NORAD_CAT_ID_1", row.get("SAT_1_ID", 0)))
                norad_2 = int(row.get("NORAD_CAT_ID_2", row.get("SAT_2_ID", 0)))
                min_range = float(row.get("MIN_RNG", row.get("MIN_RANGE_KM", 0)))
                rel_vel = float(row.get("REL_VEL", row.get("REL_VELOCITY_KMS", 0)))
                tca_str = row.get("TCA", row.get("TCA_TIME", ""))

                if norad_1 == 0 or norad_2 == 0:
                    continue

                records.append({
                    "norad_1": norad_1,
                    "norad_2": norad_2,
                    "min_range_km": min_range,
                    "rel_vel_kms": rel_vel,
                    "tca": tca_str,
                    "name_1": row.get("OBJECT_NAME_1", row.get("SAT_1_NAME", "")),
                    "name_2": row.get("OBJECT_NAME_2", row.get("SAT_2_NAME", "")),
                })
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping SOCRATES row: {e}")
                continue

    except csv.Error as e:
        logger.error(f"SOCRATES CSV parse error: {e}")

    logger.info(f"Parsed {len(records)} SOCRATES records")
    return records


async def validate_against_socrates() -> SOCRATESValidation:
    """Cross-validate our conjunction predictions against SOCRATES.

    For each SOCRATES conjunction, looks for a matching conjunction
    in our database (same NORAD ID pair). If found, computes the
    delta between our miss distance prediction and SOCRATES'.

    Returns a SOCRATESValidation object with the match list.
    """
    csv_text = await fetch_socrates_csv()
    socrates_records = parse_socrates_csv(csv_text)

    if not socrates_records:
        return SOCRATESValidation(
            matches=[],
            last_fetched=datetime.now(timezone.utc),
        )

    matches: list[SOCRATESMatch] = []

    async with AsyncSessionLocal() as session:
        for record in socrates_records:
            id_a = min(record["norad_1"], record["norad_2"])
            id_b = max(record["norad_1"], record["norad_2"])

            # Find our prediction for the same pair
            result = await session.execute(
                select(Conjunction).where(
                    (
                        (Conjunction.obj_a_id == id_a) & (Conjunction.obj_b_id == id_b)
                    ) | (
                        (Conjunction.obj_a_id == id_b) & (Conjunction.obj_b_id == id_a)
                    )
                ).order_by(Conjunction.tca_time.desc()).limit(1)
            )
            our_conj = result.scalar_one_or_none()

            our_prediction = {}
            delta = 0.0

            if our_conj:
                our_prediction = {
                    "miss_distance_km": our_conj.miss_distance_km,
                    "relative_velocity_kms": our_conj.relative_velocity_kms,
                    "risk_score": our_conj.risk_score,
                    "tier": our_conj.tier.value,
                    "tca_time": our_conj.tca_time.isoformat(),
                }
                delta = abs(our_conj.miss_distance_km - record["min_range_km"])
            else:
                our_prediction = {
                    "miss_distance_km": None,
                    "note": "No matching conjunction in our database",
                }
                delta = record["min_range_km"]

            socrates_prediction = {
                "miss_distance_km": record["min_range_km"],
                "relative_velocity_kms": record["rel_vel_kms"],
                "tca": record["tca"],
                "name_1": record["name_1"],
                "name_2": record["name_2"],
            }

            matches.append(SOCRATESMatch(
                our_prediction=our_prediction,
                socrates_prediction=socrates_prediction,
                delta_km=round(delta, 4),
                norad_ids=[record["norad_1"], record["norad_2"]],
            ))

    logger.info(
        f"SOCRATES validation: {len(matches)} comparisons, "
        f"avg delta: {sum(m.delta_km for m in matches) / max(len(matches), 1):.2f} km"
    )

    return SOCRATESValidation(
        matches=matches,
        last_fetched=datetime.now(timezone.utc),
    )
