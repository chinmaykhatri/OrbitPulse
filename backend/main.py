"""OrbitPulse — Autonomous Space Traffic Decision Engine.

Application entry point. Configures FastAPI with:
- CORS middleware for cross-origin frontend access
- X-Demo-Key middleware for POST/DELETE endpoint protection
- Lifespan handler for startup (ingestion → propagation → detection → demo seed)
- APScheduler for periodic pipeline re-runs (every 6 hours)
- Health check endpoint with pipeline readiness status
- Keep-warm pings to prevent container sleep on Railway
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
_conjunctions_found = 0
_scheduler = None


async def _run_full_pipeline() -> None:
    """Execute the complete pipeline: ingest → propagate → detect → seed demo.

    Called on startup and by APScheduler every 6 hours.
    Each stage logs its own progress. If any stage fails, subsequent
    stages still attempt to run with whatever data is available.
    """
    global _ready, _objects_loaded, _conjunctions_found

    from ingestion.pipeline import run_ingestion
    from core.engine import orbital_engine
    from core.detector import run_detection
    from core.demo_seeder import seed_demo_conjunction
    from core.fragmentation import cleanup_fragments
    from cache.position_cache import get_positions

    # Stage 1: Ingest TLE data from CelesTrak
    try:
        count = await run_ingestion()
        _objects_loaded = count
        logger.info(f"Ingestion complete: {count} objects")
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)

    # Stage 2: Load catalog and propagate orbits
    try:
        await orbital_engine.load_catalog()
        propagated = await orbital_engine.propagate_full_catalog()
        logger.info(f"Propagation complete: {propagated} objects")
    except Exception as e:
        logger.error(f"Propagation failed: {e}", exc_info=True)

    # Stage 3: Run conjunction detection (two-pass)
    try:
        # Build cached_positions dict from Redis for the detector
        cached: dict = {}
        for norad_id in list(orbital_engine._catalog.keys())[:settings.default_render_count]:
            positions = await get_positions(norad_id)
            if positions is not None:
                cached[norad_id] = positions

        if cached:
            conj_count = await run_detection(
                catalog=orbital_engine._catalog,
                timesteps=orbital_engine.get_timesteps(),
                cached_positions=cached,
            )
            _conjunctions_found = conj_count
            logger.info(f"Detection complete: {conj_count} conjunctions")
        else:
            logger.warning("No cached positions available — skipping detection")
    except Exception as e:
        logger.error(f"Detection failed: {e}", exc_info=True)

    # Stage 4: Seed demo conjunction (guarantees ACTION tier for demos)
    try:
        await seed_demo_conjunction()
    except Exception as e:
        logger.error(f"Demo seeder failed: {e}", exc_info=True)

    # Stage 5: Clean up expired fragmentation data
    try:
        await cleanup_fragments()
    except Exception as e:
        logger.error(f"Fragment cleanup failed: {e}", exc_info=True)

    _ready = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager.

    Startup sequence:
      1. Run full pipeline (ingest → propagate → detect → seed)
      2. Start APScheduler for periodic re-runs
      3. Start keep-warm ping task

    Shutdown sequence:
      1. Stop APScheduler
      2. Close Redis connection pool
    """
    global _scheduler
    logger.info("OrbitPulse starting up...")

    # Run the full pipeline on startup
    try:
        await _run_full_pipeline()
        logger.info("OrbitPulse ready — all systems operational")
    except Exception as e:
        logger.error(f"Startup pipeline failed: {e}", exc_info=True)
        logger.warning("Server running in degraded mode — health check will report not ready")

    # Start APScheduler for periodic pipeline re-runs
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.interval import IntervalTrigger

        _scheduler = AsyncIOScheduler()
        _scheduler.add_job(
            _run_full_pipeline,
            trigger=IntervalTrigger(hours=settings.ingestion_interval_hours),
            id="pipeline_rerun",
            name="Full pipeline re-run",
            replace_existing=True,
        )
        _scheduler.start()
        logger.info(f"APScheduler started: pipeline re-runs every {settings.ingestion_interval_hours}h")
    except ImportError:
        logger.warning("APScheduler not installed — periodic pipeline re-runs disabled")
    except Exception as e:
        logger.error(f"APScheduler start failed: {e}", exc_info=True)

    yield

    # Shutdown
    logger.info("OrbitPulse shutting down...")
    if _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.error(f"Scheduler shutdown error: {e}")

    try:
        from cache import close_redis
        await close_redis()
    except Exception as e:
        logger.error(f"Redis shutdown error: {e}")


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

# --- API Routers ---
from api.objects import router as objects_router
from api.conjunctions import router as conjunctions_router
from api.maneuvers import router as maneuvers_router
from api.simulation import router as simulation_router
from api.validation import router as validation_router
from api.export import router as export_router

app.include_router(objects_router)
app.include_router(conjunctions_router)
app.include_router(maneuvers_router)
app.include_router(simulation_router)
app.include_router(validation_router)
app.include_router(export_router)

# --- WebSocket ---
from ws.live import websocket_endpoint

app.websocket("/ws/live")(websocket_endpoint)


@app.get("/api/health")
async def health_check():
    """Pipeline readiness status.

    Returns ready=True only after the full startup pipeline completes
    (ingestion + propagation + detection). Frontend uses this to show loading state.
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
        "conjunctions_found": _conjunctions_found,
        "stage": status["stage"] if status else None,
        "progress_pct": status["progress_pct"] if status else None,
    }
