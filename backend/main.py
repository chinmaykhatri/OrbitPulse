"""OrbitPulse — Autonomous Space Traffic Decision Engine.

Application entry point. Configures FastAPI with:
- CORS middleware for cross-origin frontend access
- X-Demo-Key middleware for POST/DELETE endpoint protection
- Lifespan handler for startup (ingestion + propagation) and shutdown (cleanup)
- Health check endpoint with pipeline readiness status
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from middleware import DemoKeyMiddleware

logger = logging.getLogger("orbitpulse")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

settings = get_settings()

# Module-level state tracking — set by lifespan, read by health check
_ready = False
_objects_loaded = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager.

    Startup sequence:
      1. Run CelesTrak ingestion (fetch TLEs + catalog)
      2. Load catalog into orbital engine
      3. Propagate full catalog (72h window, 60s steps)
      4. Run conjunction detection (two-pass)

    Shutdown sequence:
      1. Close Redis connection pool

    If startup fails (e.g., CelesTrak is down), the server still starts
    but the health endpoint reports ready=False. The scheduled pipeline
    will retry on its configured interval.
    """
    global _ready, _objects_loaded
    logger.info("OrbitPulse starting up...")

    try:
        # Import here to avoid circular imports during module loading
        from ingestion.pipeline import run_ingestion
        from core.engine import orbital_engine
        from cache import close_redis

        # Step 1: Ingest TLE data from CelesTrak
        count = await run_ingestion()
        _objects_loaded = count
        logger.info(f"Ingestion complete: {count} objects")

        # Step 2: Load catalog and propagate orbits
        await orbital_engine.load_catalog()
        await orbital_engine.propagate_full_catalog()
        _ready = True

        logger.info("OrbitPulse ready — all systems operational")
    except Exception as e:
        logger.error(f"Startup pipeline failed: {e}", exc_info=True)
        logger.warning("Server running in degraded mode — health check will report not ready")

    yield

    logger.info("OrbitPulse shutting down...")
    try:
        from cache import close_redis
        await close_redis()
    except Exception as e:
        logger.error(f"Shutdown cleanup error: {e}")


app = FastAPI(
    title="OrbitPulse",
    description="Autonomous Space Traffic Decision Engine — real orbital data, real physics, real collision predictions.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — explicit origins, not wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# X-Demo-Key protection on POST/DELETE endpoints
app.add_middleware(DemoKeyMiddleware, secret_key=settings.demo_secret_key)


@app.get("/api/health")
async def health_check():
    """Pipeline readiness status.

    Returns ready=True only after the full startup pipeline completes
    (ingestion + propagation). Frontend uses this to show loading state.
    """
    from cache import get_pipeline_status

    status = None
    try:
        status = await get_pipeline_status()
    except Exception:
        pass

    return {
        "status": "ok",
        "ready": _ready,
        "objects_loaded": _objects_loaded,
        "stage": status["stage"] if status else None,
        "progress_pct": status["progress_pct"] if status else None,
    }
