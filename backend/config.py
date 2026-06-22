"""OrbitPulse configuration — single source for all tunable parameters.

Every threshold, URL, and credential comes from environment variables via
pydantic-settings. No hardcoded values anywhere in the codebase.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    All fields have sensible defaults for local development.
    Production values are set via Railway environment variables.
    """

    # --- Infrastructure ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/orbitpulse"
    redis_url: str = "redis://localhost:6379/0"
    claude_api_key: str = ""
    demo_secret_key: str = "orbitpulse-demo-2026"
    celestrak_base_url: str = "https://celestrak.org"
    cors_origins: str = "http://localhost:3000"

    # --- Pipeline Timing ---
    ingestion_interval_hours: int = 6
    propagation_timestep_coarse_s: int = 60
    propagation_timestep_fine_s: int = 1
    propagation_window_hours: int = 72
    fine_window_minutes: int = 10

    # --- Detection Thresholds ---
    # Coarse pass: any pair within this distance is a candidate
    coarse_threshold_km: float = 20.0
    # Fine pass: only conjunctions below this are stored
    conjunction_threshold_km: float = 10.0

    # --- Triage Tier Thresholds ---
    # ACTION: risk >= this OR (miss < action_distance AND vel > action_velocity)
    action_risk_threshold: float = 0.7
    action_distance_threshold_km: float = 1.0
    action_velocity_threshold_kms: float = 5.0
    # WATCHLIST: risk >= this AND miss < watchlist_distance
    watchlist_risk_threshold: float = 0.3
    watchlist_distance_threshold_km: float = 5.0

    # --- Maneuver Planner ---
    maneuver_candidates: int = 5
    maneuver_delta_v_steps: list[float] = [0.05, 0.10, 0.25, 0.50, 1.0]

    # --- Negotiation ---
    max_negotiation_rounds: int = 4

    # --- Fragmentation Simulation ---
    default_fragment_count: int = 50
    max_fragment_count: int = 200
    fragment_expiry_minutes: int = 60
    fragment_velocity_mean_ms: float = 50.0
    fragment_velocity_cap_ms: float = 300.0

    # --- Globe Rendering ---
    default_render_count: int = 5000

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance — constructed once, reused everywhere."""
    return Settings()
