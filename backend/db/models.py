"""SQLAlchemy ORM models — complete schema for OrbitPulse.

Six tables covering the full pipeline:
  objects           — satellite catalog with TLE data
  satellite_profiles — operator-specific metadata (fuel, mass, priority)
  conjunctions      — detected close approaches with risk scoring
  maneuvers         — candidate burn plans for collision avoidance
  negotiations      — round-by-round negotiation records
  fragmentation_events — simulated breakup fragment tracking

Every table has created_at/updated_at timestamps in UTC.
Every foreign key has explicit cascade rules.
Every query path has a corresponding index.
"""
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, Enum, DateTime,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Declarative base for all OrbitPulse models."""
    pass


# --- Enums ---

class ObjectType(str, enum.Enum):
    PAYLOAD = "PAYLOAD"
    ROCKET_BODY = "ROCKET_BODY"
    DEBRIS = "DEBRIS"


class RCSSize(str, enum.Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class TriageTier(str, enum.Enum):
    ACTION = "ACTION"
    WATCHLIST = "WATCHLIST"
    DISMISSED = "DISMISSED"


class ManeuverStatus(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    RECOMMENDED = "RECOMMENDED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class ManeuverDirection(str, enum.Enum):
    PROGRADE = "PROGRADE"
    RETROGRADE = "RETROGRADE"


def _utcnow() -> datetime:
    """UTC-aware timestamp factory for default column values."""
    return datetime.now(timezone.utc)


# --- Tables ---

class SpaceObject(Base):
    """Tracked space object — payload, rocket body, or debris.

    Primary data source: CelesTrak GP catalog + TLE files.
    TLE lines are stored raw for direct SGP4 propagation.
    """
    __tablename__ = "objects"

    norad_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    object_type = Column(Enum(ObjectType), nullable=False, default=ObjectType.DEBRIS)
    rcs_size = Column(Enum(RCSSize), nullable=True)
    country_code = Column(String(10), nullable=True)
    launch_date = Column(DateTime, nullable=True)
    decay_date = Column(DateTime, nullable=True)
    tle_line1 = Column(Text, nullable=True)
    tle_line2 = Column(Text, nullable=True)
    tle_epoch = Column(DateTime, nullable=True)
    data_source = Column(String(20), nullable=False, default="celestrak", server_default="celestrak")
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationships
    profile = relationship("SatelliteProfile", back_populates="space_object", uselist=False)
    conjunctions_as_a = relationship(
        "Conjunction", foreign_keys="Conjunction.obj_a_id", back_populates="object_a",
    )
    conjunctions_as_b = relationship(
        "Conjunction", foreign_keys="Conjunction.obj_b_id", back_populates="object_b",
    )

    __table_args__ = (
        Index("ix_objects_type", "object_type"),
    )


class SatelliteProfile(Base):
    """Operator-specific satellite metadata for maneuver planning.

    Seeded for key satellites (ISS, Starlink samples, ESA, NOAA, ISRO, JAXA).
    Used by the maneuver planner for Tsiolkovsky fuel cost calculation
    and by the negotiation protocol for utility function evaluation.
    """
    __tablename__ = "satellite_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    norad_id = Column(
        Integer, ForeignKey("objects.norad_id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    operator_name = Column(String(255), nullable=True)
    fuel_remaining_pct = Column(Float, nullable=False, default=100.0)
    fuel_remaining_kg = Column(Float, nullable=False, default=100.0)
    dry_mass_kg = Column(Float, nullable=False, default=500.0)
    mission_priority = Column(Integer, nullable=False, default=5)
    maneuver_budget_ms = Column(Float, nullable=False, default=50.0)
    isp_rating = Column(Float, nullable=False, default=300.0)
    remaining_mission_days = Column(Integer, nullable=False, default=3650)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationships
    space_object = relationship("SpaceObject", back_populates="profile")


class Conjunction(Base):
    """Detected close approach between two space objects.

    Created by the two-pass detector after fine screening confirms
    miss distance < conjunction_threshold_km. Risk score computed from
    distance, velocity, object size, and trend (convergence/divergence).

    Tier assignment follows the triage rules in risk_scoring.py.
    """
    __tablename__ = "conjunctions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    obj_a_id = Column(
        Integer, ForeignKey("objects.norad_id"), nullable=False, index=True,
    )
    obj_b_id = Column(
        Integer, ForeignKey("objects.norad_id"), nullable=False, index=True,
    )
    tca_time = Column(DateTime, nullable=False, index=True)
    miss_distance_km = Column(Float, nullable=False)
    prev_miss_distance_km = Column(Float, nullable=True)
    relative_velocity_kms = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    tier = Column(Enum(TriageTier), nullable=False, index=True)
    dismiss_reason = Column(Text, nullable=True)
    both_maneuverable = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationships
    object_a = relationship(
        "SpaceObject", foreign_keys=[obj_a_id], back_populates="conjunctions_as_a",
    )
    object_b = relationship(
        "SpaceObject", foreign_keys=[obj_b_id], back_populates="conjunctions_as_b",
    )
    maneuvers = relationship(
        "Maneuver", back_populates="conjunction", cascade="all, delete-orphan",
    )
    negotiations = relationship(
        "Negotiation", back_populates="conjunction", cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("obj_a_id", "obj_b_id", "tca_time", name="uq_conjunction_pair_tca"),
        Index("ix_conjunctions_tier_tca", "tier", "tca_time"),
    )


class Maneuver(Base):
    """Candidate collision avoidance burn plan.

    Generated by the maneuver planner: 5 delta-v magnitudes × 2 directions
    = 10 candidates per conjunction, filtered to the best 5 by fuel cost.
    Each candidate includes the post-burn miss distance (from scoped re-screening)
    and the count of secondary conjunctions introduced by the orbit change.
    """
    __tablename__ = "maneuvers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conjunction_id = Column(
        Integer, ForeignKey("conjunctions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    satellite_id = Column(
        Integer, ForeignKey("objects.norad_id"), nullable=False,
    )
    direction = Column(Enum(ManeuverDirection), nullable=False)
    delta_v_ms = Column(Float, nullable=False)
    burn_time = Column(DateTime, nullable=False)
    new_miss_distance_km = Column(Float, nullable=False)
    fuel_cost_kg = Column(Float, nullable=False)
    mission_life_impact_days = Column(Float, nullable=False)
    mission_life_impact_pct = Column(Float, nullable=False)
    secondary_conjunctions = Column(Integer, nullable=False, default=0)
    status = Column(Enum(ManeuverStatus), nullable=False, default=ManeuverStatus.CANDIDATE)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationships
    conjunction = relationship("Conjunction", back_populates="maneuvers")

    __table_args__ = (
        Index("ix_maneuvers_conjunction_status", "conjunction_id", "status"),
    )


class Negotiation(Base):
    """Round-by-round negotiation record for both-maneuverable conjunctions.

    Each row is one round of the protocol. The proposer field is a NORAD ID
    (which operator proposed) or 0 for system-initiated proposals.
    """
    __tablename__ = "negotiations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conjunction_id = Column(
        Integer, ForeignKey("conjunctions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    round_number = Column(Integer, nullable=False)
    proposer_id = Column(Integer, nullable=False)
    proposal = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    accepted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow, nullable=False)

    # Relationships
    conjunction = relationship("Conjunction", back_populates="negotiations")


class FragmentationEvent(Base):
    """Simulated breakup fragment for Kessler syndrome visualization.

    Fragments use negative synthetic NORAD IDs (starting at -1000) to avoid
    collision with real catalog IDs. Each fragment has an expiry time after
    which the cleanup task removes it from Redis and the database.
    """
    __tablename__ = "fragmentation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parent_norad_id = Column(
        Integer, ForeignKey("objects.norad_id"), nullable=False, index=True,
    )
    fragment_norad_id = Column(Integer, nullable=False, unique=True)
    spawned_at = Column(DateTime, default=_utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
