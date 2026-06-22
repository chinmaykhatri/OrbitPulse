# 🛰️ OrbitPulse

**Autonomous Space Traffic Decision Engine** — real orbital data, real physics, real collision predictions.

OrbitPulse is a production-grade system that ingests live satellite catalog data from CelesTrak, propagates 25,000+ orbits using SGP4, detects conjunction threats with two-pass screening, plans collision avoidance maneuvers, and runs agent-to-agent operator negotiations — all visualized on a real-time 3D globe command center.

---

## What It Does

| Capability | How It Works |
|---|---|
| **Live Orbital Data** | Ingests TLE data from CelesTrak (same source the satellite industry uses) |
| **SGP4 Propagation** | NORAD-standard orbital mechanics, vectorized across 25,000+ objects |
| **Conjunction Detection** | Two-pass screening: 60s coarse → 1s fine, with altitude band pre-filter |
| **Risk Scoring** | Weighted formula: proximity (50%), velocity (30%), size (20%), trend multiplier |
| **Triage Funnel** | ACTION / WATCHLIST / DISMISSED — deterministic tier assignment |
| **Maneuver Planning** | Tsiolkovsky-based delta-v burns with fuel cost and mission life impact |
| **Operator Negotiation** | Game-theoretic utility functions for both-maneuverable conjunction resolution |
| **Fragmentation Simulation** | Kessler syndrome visualization with NASA breakup model velocity distributions |
| **ISS Validation** | Self-validating position against TLE epoch — cross-check with n2yo.com |
| **SOCRATES Cross-Check** | Live comparison against CelesTrak's independent conjunction predictions |

## Architecture

```
CelesTrak → Ingestion → SGP4 Engine → Two-Pass Detector → Triage Funnel
                                                              ↓
                                              Maneuver Planner ← Satellite Profiles
                                                              ↓
                                              Negotiation Protocol (both-maneuverable)
                                                              ↓
Frontend ← WebSocket ← API ← Decision Pipeline ← Fragmentation Simulator
```

**Backend**: FastAPI (Python 3.12) — SGP4 orbital engine, conjunction detector, maneuver planner  
**Frontend**: Next.js 14 + CesiumJS — live 3D globe command center  
**Database**: PostgreSQL (Neon) — satellite catalog, conjunctions, maneuvers, negotiations  
**Cache**: Redis — position arrays, simulation locks, pipeline status  
**AI**: Claude API — natural language narration with deterministic template fallback  

## Quick Start

```bash
# Start infrastructure (Postgres + Redis)
docker-compose up -d db redis

# Backend
cd backend
cp .env.example .env
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1

# Frontend
cd frontend
npm install
npm run dev
```

> **Note**: `--workers 1` is required. The orbital engine maintains in-memory state (position matrices) that must be consistent within a single process.

## What Is Real and What Is Simulated

**Real and verifiable**: every object, every orbit, every position, every conjunction prediction. Same data source the industry uses, cross-checkable against independent trackers.

**Simulated and disclosed**: maneuver execution, operator fuel profiles, fragmentation clouds. The math is real. The execution is simulated.

**Demo mode**: labeled with a visible badge. Seeded ACTION-tier conjunctions ensure the demo always has interesting data. SOCRATES validation is live. ISS verification is self-validating.

## Tech Stack

- Python 3.12, FastAPI, SQLAlchemy, Alembic, SGP4, Skyfield, NumPy, SciPy
- Next.js 14, TypeScript, CesiumJS (resium), Recharts
- PostgreSQL, Redis, Docker Compose
- Claude API (Anthropic) for natural language narration
- Deployed on Railway (backend) + Vercel (frontend) + Neon (database)

## License

MIT
